import math
import difflib
import re
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

try:
    import streamlit as st
except ImportError:  # hanya untuk test helper di environment tanpa Streamlit
    st = None


# ============================================================
# ONLINE NPSN CONFIG
# ============================================================

KEMENDIKDASMEN_NPSN_URL = (
    "https://referensi.data.kemendikdasmen.go.id/pendidikan/npsn/{npsn}"
)
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
GOOGLE_PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
HTTP_TIMEOUT_SECONDS = 15
HTTP_HEADERS = {
    "User-Agent": "AutoTimestamp-NPSN/10.0 (Streamlit; NPSN location lookup)",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.6",
}


# ============================================================
# NORMALIZATION HELPERS
# ============================================================


def _normalize_npsn(value):
    if value is None:
        return ""
    value = str(value).strip().upper()
    return re.sub(r"\s+", "", value)


def _validate_npsn_format(npsn):
    npsn = _normalize_npsn(npsn)
    if not npsn:
        raise ValueError("NPSN belum diisi.")
    if not re.fullmatch(r"[A-Z0-9]{8}", npsn):
        raise ValueError(
            "Format NPSN harus 8 karakter huruf/angka tanpa spasi. "
            "Contoh: 20212345."
        )
    return npsn


def _collapse_spaces(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_label(value):
    return re.sub(r"[^a-z0-9]+", "", _collapse_spaces(value).lower())


def _clean_region_prefix(value):
    value = _collapse_spaces(value)
    if not value:
        return ""

    # Prefix mengikuti format yang umum tampil di Referensi Data.
    # Dilakukan berulang supaya kombinasi seperti "PROV. D.K.I. ..."
    # tetap bersih tanpa menghapus bagian nama wilayahnya.
    patterns = [
        r"^PROVINSI\s+",
        r"^PROPINSI\s+",
        r"^PROV\.\s*",
        r"^KABUPATEN\s+",
        r"^KAB\.\s*",
        r"^KAB\s+",
        r"^KOTA\s+ADMINISTRASI\s+",
        r"^KOTA\s+ADM\.\s*",
        r"^KOTA\s+",
        r"^KECAMATAN\s+",
        r"^KEC\.\s*",
        r"^KEC\s+",
        r"^KELURAHAN\s+",
        r"^KEL\.\s*",
        r"^DESA\s+",
    ]

    previous = None
    while previous != value:
        previous = value
        for pattern in patterns:
            value = re.sub(pattern, "", value, flags=re.IGNORECASE).strip()

    return value


def _pretty_region(value):
    value = _clean_region_prefix(value)
    if not value:
        return ""
    # title() mempertahankan bentuk seperti D.K.I. Jakarta dengan cukup baik,
    # sekaligus mengubah "PURWAKARTA" menjadi "Purwakarta".
    return value.title()


def _parse_coordinate(value, field_name):
    raw = _collapse_spaces(value)
    if not raw:
        raise ValueError(f"{field_name} kosong pada data NPSN resmi.")

    # Beberapa sumber menulis koma sebagai pemisah desimal.
    if "," in raw and "." not in raw:
        raw = raw.replace(",", ".")

    match = re.search(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)", raw)
    if not match:
        raise ValueError(f"{field_name} tidak valid: {value}")

    number = float(match.group(0))

    if field_name.lower().startswith("lat") and not (-90 <= number <= 90):
        raise ValueError(f"Latitude di luar rentang: {number}")
    if field_name.lower().startswith("long") and not (-180 <= number <= 180):
        raise ValueError(f"Longitude di luar rentang: {number}")

    return number


def _extract_token_value(tokens, aliases):
    """Ambil nilai setelah label dari token HTML yang sudah dibersihkan.

    Halaman Referensi Data kadang memisahkan label, ':', dan nilai menjadi
    elemen HTML terpisah. Helper ini mendukung kedua bentuk tersebut.
    """
    alias_norms = [(_normalize_label(alias), alias) for alias in aliases]

    for index, token in enumerate(tokens):
        token_text = _collapse_spaces(token)
        token_norm = _normalize_label(token_text)

        for alias_norm, alias in alias_norms:
            # Bentuk: "Lintang: -6.1234" / "NPSN : 20212345"
            if token_norm.startswith(alias_norm) and len(token_norm) > len(alias_norm):
                match = re.match(
                    rf"^{re.escape(alias)}\s*:?\s*(.+)$",
                    token_text,
                    flags=re.IGNORECASE,
                )
                if match and _collapse_spaces(match.group(1)):
                    return _collapse_spaces(match.group(1))

            # Bentuk: token label sendiri, lalu ':' dan nilai di token berikutnya.
            if token_norm == alias_norm:
                for next_index in range(index + 1, min(index + 5, len(tokens))):
                    candidate = _collapse_spaces(tokens[next_index])
                    if not candidate or candidate in {":", "-"}:
                        continue
                    if _normalize_label(candidate) in {norm for norm, _ in alias_norms}:
                        break
                    return candidate.lstrip(":").strip()

    return ""



# ============================================================
# OFFICIAL KEMENDIKDASMEN LOOKUP
# ============================================================


def _parse_kemendikdasmen_npsn_html(html_text, requested_npsn, source_url):
    soup = BeautifulSoup(html_text, "html.parser")
    tokens = list(soup.stripped_strings)
    page_text = "\n".join(tokens)

    page_npsn = _extract_token_value(tokens, ["NPSN"])
    page_npsn = _normalize_npsn(page_npsn)

    if not page_npsn:
        raise ValueError(
            "NPSN tidak ditemukan pada halaman Referensi Data. "
            "Kemungkinan NPSN tidak valid atau struktur situs sedang berubah."
        )

    if page_npsn != requested_npsn:
        raise ValueError(
            f"Validasi exact-match gagal. Diminta {requested_npsn}, "
            f"tetapi halaman mengembalikan {page_npsn}."
        )

    nama_sekolah = _extract_token_value(tokens, ["Nama"])
    alamat = _extract_token_value(tokens, ["Alamat"])

    desa = _extract_token_value(
        tokens,
        ["Desa/Kelurahan", "Desa / Kelurahan", "Kelurahan/Desa"],
    )
    kecamatan = _extract_token_value(
        tokens,
        ["Kecamatan/Kota (LN)", "Kecamatan", "Kec."],
    )
    kabupaten_kota = _extract_token_value(
        tokens,
        [
            "Kab.-Kota/Negara (LN)",
            "Kabupaten/Kota",
            "Kab.-Kota",
            "Kabupaten",
            "Kota",
        ],
    )
    provinsi = _extract_token_value(
        tokens,
        ["Propinsi/Luar Negeri (LN)", "Provinsi/Luar Negeri (LN)", "Provinsi", "Propinsi"],
    )

    # Koordinat pada halaman resmi berada di bagian Peta dan biasanya berbentuk
    # "Lintang: -6.x" / "Bujur: 107.x". Regex menjadi fallback paling kuat.
    lat_match = re.search(
        r"Lintang\s*:?\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))",
        page_text,
        flags=re.IGNORECASE,
    )
    lon_match = re.search(
        r"Bujur\s*:?\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))",
        page_text,
        flags=re.IGNORECASE,
    )

    if not lat_match:
        lat_value = _extract_token_value(tokens, ["Lintang", "Latitude"])
    else:
        lat_value = lat_match.group(1)

    if not lon_match:
        lon_value = _extract_token_value(tokens, ["Bujur", "Longitude"])
    else:
        lon_value = lon_match.group(1)

    latitude = _parse_coordinate(lat_value, "Latitude")
    longitude = _parse_coordinate(lon_value, "Longitude")

    # 0,0 adalah placeholder/residu. Jangan langsung error di parser karena
    # V8.7 menyediakan fallback geocoding OPSIONAL. Logic utama tetap memakai
    # koordinat resmi jika tersedia.
    official_coordinate_valid = not (
        abs(latitude) < 1e-12 and abs(longitude) < 1e-12
    )

    desa_pretty = _pretty_region(desa)
    kecamatan_pretty = _pretty_region(kecamatan)
    kab_pretty = _pretty_region(kabupaten_kota)
    prov_pretty = _pretty_region(provinsi)

    first_part = desa_pretty or kecamatan_pretty
    location_parts = [part for part in [first_part, kab_pretty, prov_pretty] if part]

    if len(location_parts) < 2:
        raise ValueError(
            "Data wilayah dari Referensi Data belum cukup untuk membentuk lokasi timestamp."
        )

    location = ", ".join(location_parts)

    return {
        "npsn": requested_npsn,
        "nama_sekolah": _collapse_spaces(nama_sekolah),
        "alamat": _collapse_spaces(alamat),
        "latitude": latitude,
        "longitude": longitude,
        "official_latitude": latitude,
        "official_longitude": longitude,
        "official_coordinate_valid": official_coordinate_valid,
        "coordinate_source_type": "official" if official_coordinate_valid else "official_missing",
        "location": location,
        "desa": desa_pretty,
        "kecamatan": kecamatan_pretty,
        "kabupaten_kota": kab_pretty,
        "provinsi": prov_pretty,
        "source_url": source_url,
        "source_name": "Referensi Data Kemendikdasmen",
    }


def lookup_npsn_online(npsn):
    npsn = _validate_npsn_format(npsn)
    source_url = KEMENDIKDASMEN_NPSN_URL.format(npsn=quote(npsn, safe=""))

    try:
        response = requests.get(
            source_url,
            headers=HTTP_HEADERS,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise ValueError(
            "Tidak dapat terhubung ke Referensi Data Kemendikdasmen. "
            "Periksa koneksi internet lalu coba lagi."
        ) from exc

    if response.status_code != 200:
        raise ValueError(
            f"Referensi Data Kemendikdasmen mengembalikan HTTP {response.status_code}. "
            "Coba lagi beberapa saat."
        )

    return _parse_kemendikdasmen_npsn_html(
        response.text,
        requested_npsn=npsn,
        source_url=source_url,
    )


# ============================================================
# SECOND-LAYER LOCATION VALIDATION (OPENSTREETMAP / NOMINATIM)
# ============================================================


def _normalize_region_for_compare(value):
    value = _collapse_spaces(value).lower()
    value = value.replace("d.k.i.", "dki").replace("d.i.", "di")
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()

    aliases = {
        "dki jakarta": "jakarta",
        "daerah khusus ibukota jakarta": "jakarta",
        "daerah khusus jakarta": "jakarta",
        "di yogyakarta": "yogyakarta",
        "daerah istimewa yogyakarta": "yogyakarta",
    }
    if value in aliases:
        return aliases[value]

    stop_words = {
        "kabupaten",
        "kab",
        "kota",
        "provinsi",
        "propinsi",
        "province",
        "regency",
        "city",
        "municipality",
    }
    words = [word for word in value.split() if word not in stop_words]
    return " ".join(words)


def _region_matches(official_value, reverse_value):
    official = _normalize_region_for_compare(official_value)
    reverse = _normalize_region_for_compare(reverse_value)
    if not official or not reverse:
        return None
    return official == reverse or official in reverse or reverse in official


def reverse_validate_location(
    latitude,
    longitude,
    official_desa,
    official_kecamatan,
    official_kabupaten,
    official_provinsi,
    zoom=10,
):
    params = {
        "format": "jsonv2",
        "lat": f"{latitude:.8f}",
        "lon": f"{longitude:.8f}",
        "zoom": int(zoom),
        "addressdetails": 1,
        "accept-language": "id",
    }

    try:
        response = requests.get(
            NOMINATIM_REVERSE_URL,
            params=params,
            headers=HTTP_HEADERS,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            raise requests.RequestException(f"HTTP {response.status_code}")
        payload = response.json()
    except Exception as exc:
        return {
            "status": "unavailable",
            "message": "Validasi peta kedua sedang tidak tersedia.",
            "reverse_desa": "",
            "reverse_kecamatan": "",
            "reverse_kabupaten": "",
            "reverse_provinsi": "",
            "display_name": "",
            "error": str(exc),
        }

    address = payload.get("address") or {}
    reverse_desa = (
        address.get("village")
        or address.get("suburb")
        or address.get("hamlet")
        or address.get("neighbourhood")
        or ""
    )
    reverse_kecamatan = (
        address.get("city_district")
        or address.get("subdistrict")
        or address.get("municipality")
        or address.get("district")
        or ""
    )
    reverse_kabupaten = (
        address.get("county")
        or address.get("city")
        or address.get("municipality")
        or address.get("town")
        or address.get("state_district")
        or ""
    )
    reverse_provinsi = address.get("state") or address.get("region") or ""
    display_name = _collapse_spaces(payload.get("display_name", ""))

    desa_match = _region_matches(official_desa, reverse_desa)
    kec_match = _region_matches(official_kecamatan, reverse_kecamatan)
    kab_match = _region_matches(official_kabupaten, reverse_kabupaten)
    prov_match = _region_matches(official_provinsi, reverse_provinsi)

    explicit_mismatches = []
    if desa_match is False:
        explicit_mismatches.append("desa/kelurahan")
    if kec_match is False:
        explicit_mismatches.append("kecamatan")
    if kab_match is False:
        explicit_mismatches.append("kabupaten/kota")
    if prov_match is False:
        explicit_mismatches.append("provinsi")

    if explicit_mismatches:
        return {
            "status": "mismatch",
            "message": (
                "Koordinat resmi tidak cocok dengan hasil reverse-geocoding pada "
                + " dan ".join(explicit_mismatches)
                + ". Generate diblokir agar tidak memakai lokasi yang meragukan."
            ),
            "reverse_desa": reverse_desa,
            "reverse_kecamatan": reverse_kecamatan,
            "reverse_kabupaten": reverse_kabupaten,
            "reverse_provinsi": reverse_provinsi,
            "display_name": display_name,
            "desa_match": desa_match,
            "kec_match": kec_match,
            "kab_match": kab_match,
            "prov_match": prov_match,
        }

    if kab_match is True and prov_match is True:
        status = "verified"
        message = (
            "Kabupaten/kota dan provinsi cocok dengan posisi koordinat. "
            "Kecamatan/desa tidak menunjukkan konflik."
        )
    else:
        status = "partial"
        message = (
            "Validator peta belum bisa memverifikasi seluruh wilayah wajib. "
            "Generate diblokir agar hanya data yang benar-benar terverifikasi yang dipakai."
        )

    return {
        "status": status,
        "message": message,
        "reverse_desa": reverse_desa,
        "reverse_kecamatan": reverse_kecamatan,
        "reverse_kabupaten": reverse_kabupaten,
        "reverse_provinsi": reverse_provinsi,
        "display_name": display_name,
        "desa_match": desa_match,
        "kec_match": kec_match,
        "kab_match": kab_match,
        "prov_match": prov_match,
    }


# ============================================================
# OPTIONAL STRICT FALLBACK GEOCODING
# ============================================================


def _normalize_school_name(value):
    value = _collapse_spaces(value).lower()
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    words = [
        word for word in value.split()
        if word not in {"paud", "pos", "sps", "kb", "tk", "ra", "sd", "smp", "sma", "smk", "negeri", "swasta"}
    ]
    return " ".join(words).strip()


def _school_name_similarity(official_name, candidate_name):
    official = _normalize_school_name(official_name)
    candidate = _normalize_school_name(candidate_name)
    if not official or not candidate:
        return 0.0

    ratio = difflib.SequenceMatcher(None, official, candidate).ratio()
    official_tokens = set(official.split())
    candidate_tokens = set(candidate.split())
    overlap = (
        len(official_tokens & candidate_tokens) / max(1, len(official_tokens))
    )
    return max(ratio, overlap)


def _distance_meters(lat1, lon1, lat2, lon2):
    radius = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))


def _nominatim_search(query):
    params = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        "namedetails": 1,
        "extratags": 1,
        "limit": 5,
        "countrycodes": "id",
        "accept-language": "id",
    }
    response = requests.get(
        NOMINATIM_SEARCH_URL,
        params=params,
        headers=HTTP_HEADERS,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise requests.RequestException(f"Nominatim search HTTP {response.status_code}")
    payload = response.json()
    return payload if isinstance(payload, list) else []


def _google_geocode_search(query, api_key):
    if not _collapse_spaces(api_key):
        return []
    params = {
        "address": query,
        "region": "id",
        "language": "id",
        "key": api_key,
    }
    response = requests.get(
        GOOGLE_GEOCODE_URL,
        params=params,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        detail = _collapse_spaces(response.text)[:300]
        raise requests.RequestException(
            f"Google Geocoding HTTP {response.status_code}: {detail}"
        )
    payload = response.json() or {}
    status = payload.get("status")
    if status == "ZERO_RESULTS":
        return []
    if status != "OK":
        message = _collapse_spaces(payload.get("error_message", ""))
        raise requests.RequestException(
            f"Google Geocoding status {status}: {message or 'tanpa detail'}"
        )
    return payload.get("results") or []




def _google_api_key_is_configured(api_key):
    value = _collapse_spaces(api_key)
    if not value:
        return False
    lowered = value.lower()
    placeholders = [
        "isi-api-key",
        "your-api-key",
        "google_maps_api_key",
        "replace-me",
    ]
    return not any(token in lowered for token in placeholders)


def _google_places_text_search(query, api_key):
    if not _google_api_key_is_configured(api_key):
        return []

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.location,places.addressComponents,places.types,places.primaryType"
        ),
    }
    payload = {
        "textQuery": query,
        "languageCode": "id",
        "regionCode": "ID",
        "maxResultCount": 10,
    }
    response = requests.post(
        GOOGLE_PLACES_TEXT_SEARCH_URL,
        headers=headers,
        json=payload,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        detail = _collapse_spaces(response.text)[:350]
        raise requests.RequestException(
            f"Google Places Text Search HTTP {response.status_code}: {detail}"
        )
    data = response.json() or {}
    return data.get("places") or []


def _google_component_texts(address_components):
    values = []
    for component in address_components or []:
        long_text = component.get("longText") or component.get("long_name") or ""
        short_text = component.get("shortText") or component.get("short_name") or ""
        if long_text:
            values.append(_collapse_spaces(long_text))
        if short_text:
            values.append(_collapse_spaces(short_text))
    return values


def _match_official_against_google_values(official_value, values):
    if not official_value:
        return None
    for value in values:
        match = _region_matches(official_value, value)
        if match is True:
            return True
    return False if values else None


def _google_region_validation(
    formatted_address,
    address_components,
    official_desa,
    official_kecamatan,
    official_kabupaten,
    official_provinsi,
):
    component_values = _google_component_texts(address_components)
    comparison_values = list(component_values)
    if formatted_address:
        comparison_values.append(_collapse_spaces(formatted_address))

    desa_match = _match_official_against_google_values(official_desa, comparison_values)
    kec_match = _match_official_against_google_values(official_kecamatan, comparison_values)
    kab_match = _match_official_against_google_values(official_kabupaten, comparison_values)
    prov_match = _match_official_against_google_values(official_provinsi, comparison_values)

    local_expected = bool(official_desa or official_kecamatan)
    local_confirmed = desa_match is True or kec_match is True
    strict_ok = (
        kab_match is True
        and prov_match is True
        and (not local_expected or local_confirmed)
    )

    return {
        "status": "verified" if strict_ok else "mismatch",
        "desa_match": desa_match,
        "kec_match": kec_match,
        "kab_match": kab_match,
        "prov_match": prov_match,
        "local_confirmed": local_confirmed,
        "formatted_address": _collapse_spaces(formatted_address),
        "component_values": component_values,
        "message": (
            "Wilayah Google cocok dengan data resmi NPSN."
            if strict_ok
            else "Wilayah Google belum cocok lengkap dengan data resmi NPSN."
        ),
    }


def _google_geocode_candidates(query, api_key):
    candidates = []
    for item in _google_geocode_search(query, api_key):
        location = ((item.get("geometry") or {}).get("location") or {})
        try:
            lat = float(location.get("lat"))
            lon = float(location.get("lng"))
        except (TypeError, ValueError):
            continue
        candidates.append(
            {
                "latitude": lat,
                "longitude": lon,
                "formatted_address": _collapse_spaces(item.get("formatted_address", "")),
                "address_components": item.get("address_components") or [],
                "location_type": _collapse_spaces(
                    ((item.get("geometry") or {}).get("location_type") or "")
                ).upper(),
                "place_id": _collapse_spaces(item.get("place_id", "")),
                "types": item.get("types") or [],
            }
        )
    return candidates


def _google_geocode_is_high_precision(candidate):
    location_type = str(candidate.get("location_type") or "").upper()
    types = {str(x).lower() for x in (candidate.get("types") or [])}
    precise_types = {
        "school",
        "premise",
        "establishment",
        "point_of_interest",
        "university",
    }
    return location_type == "ROOFTOP" or bool(types & precise_types)


def _merge_google_geocode_consensus(candidates, radius_meters=120):
    """Gabungkan hasil geocoding dari query berbeda yang jatuh di titik hampir sama."""
    merged = []
    for candidate in candidates:
        attached = False
        for group in merged:
            distance = _distance_meters(
                candidate["latitude"], candidate["longitude"],
                group["latitude"], group["longitude"],
            )
            if distance <= radius_meters:
                group["query_ids"].add(candidate.get("query_id", ""))
                group["queries"].append(candidate.get("query", ""))
                group["members"].append(candidate)
                if _google_geocode_is_high_precision(candidate) and not _google_geocode_is_high_precision(group):
                    query_ids = group["query_ids"]
                    queries = group["queries"]
                    members = group["members"]
                    group.update(candidate)
                    group["query_ids"] = query_ids
                    group["queries"] = queries
                    group["members"] = members
                attached = True
                break
        if not attached:
            item = dict(candidate)
            item["query_ids"] = {candidate.get("query_id", "")}
            item["queries"] = [candidate.get("query", "")]
            item["members"] = [candidate]
            merged.append(item)
    merged.sort(
        key=lambda c: (
            len({q for q in c.get("query_ids", set()) if q}),
            1 if _google_geocode_is_high_precision(c) else 0,
        ),
        reverse=True,
    )
    return merged


def _google_place_is_school_like(place):
    types = {str(x).lower() for x in (place.get("types") or [])}
    primary = str(place.get("primaryType") or "").lower()
    if primary:
        types.add(primary)
    educational_types = {
        "school",
        "preschool",
        "primary_school",
        "secondary_school",
        "child_care_agency",
        "university",
        "educational_institution",
    }
    return bool(types & educational_types)


def _build_google_places_candidates(
    query_specs,
    school_name,
    desa,
    kecamatan,
    kabupaten_kota,
    provinsi,
    api_key,
):
    by_place_id = {}
    errors = []

    if not _google_api_key_is_configured(api_key):
        return [], ["GOOGLE_MAPS_API_KEY belum dikonfigurasi."]

    for query_id, query in query_specs:
        try:
            places = _google_places_text_search(query, api_key)
        except Exception as exc:
            errors.append(f"{query_id}: {exc}")
            continue

        for place in places:
            location = place.get("location") or {}
            try:
                lat = float(location.get("latitude"))
                lon = float(location.get("longitude"))
            except (TypeError, ValueError):
                continue

            display_name_obj = place.get("displayName") or {}
            candidate_name = _collapse_spaces(
                display_name_obj.get("text") if isinstance(display_name_obj, dict) else display_name_obj
            )
            formatted_address = _collapse_spaces(place.get("formattedAddress", ""))
            name_similarity = _school_name_similarity(school_name, candidate_name)
            region_validation = _google_region_validation(
                formatted_address,
                place.get("addressComponents") or [],
                desa,
                kecamatan,
                kabupaten_kota,
                provinsi,
            )
            school_like = _google_place_is_school_like(place)

            # Google Places boleh menjadi kandidat utama sendiri, tetapi harus
            # sangat kuat: nama mirip, wilayah resmi cocok sampai level lokal,
            # dan tipenya menyerupai fasilitas pendidikan.
            min_similarity = 0.72 if school_like else 0.92
            strict_ok = (
                region_validation.get("status") == "verified"
                and name_similarity >= min_similarity
                and (school_like or name_similarity >= 0.92)
            )
            if not strict_ok:
                continue

            place_id = _collapse_spaces(place.get("id", "")) or f"{lat:.7f},{lon:.7f}"
            score = name_similarity + (0.12 if school_like else 0.0)
            existing = by_place_id.get(place_id)
            if existing is None:
                by_place_id[place_id] = {
                    "provider": "Google Places (New)",
                    "place_id": place_id,
                    "query_ids": {query_id},
                    "queries": [query],
                    "latitude": lat,
                    "longitude": lon,
                    "candidate_name": candidate_name,
                    "display_name": formatted_address,
                    "name_similarity": name_similarity,
                    "school_like": school_like,
                    "validation": region_validation,
                    "score": score,
                    "types": place.get("types") or [],
                }
            else:
                existing["query_ids"].add(query_id)
                existing["queries"].append(query)
                if score > existing["score"]:
                    existing.update(
                        {
                            "latitude": lat,
                            "longitude": lon,
                            "candidate_name": candidate_name,
                            "display_name": formatted_address,
                            "name_similarity": name_similarity,
                            "school_like": school_like,
                            "validation": region_validation,
                            "score": score,
                            "types": place.get("types") or [],
                        }
                    )

    results = list(by_place_id.values())
    results.sort(
        key=lambda c: (
            len(c.get("query_ids") or []),
            c.get("score", 0),
        ),
        reverse=True,
    )
    return results, errors


def _fallback_candidate_is_strictly_valid(
    latitude,
    longitude,
    official_desa,
    official_kecamatan,
    official_kabupaten,
    official_provinsi,
):
    validation = reverse_validate_location(
        latitude,
        longitude,
        official_desa,
        official_kecamatan,
        official_kabupaten,
        official_provinsi,
        zoom=18,
    )
    if validation.get("status") != "verified":
        return False, validation

    # Untuk fallback kita lebih ketat daripada logic utama: selain kabupaten +
    # provinsi wajib cocok, minimal salah satu level lokal (desa/kecamatan)
    # juga harus terkonfirmasi bila datanya tersedia di master NPSN.
    local_expected = bool(official_desa or official_kecamatan)
    local_confirmed = (
        validation.get("desa_match") is True
        or validation.get("kec_match") is True
    )
    if local_expected and not local_confirmed:
        validation = dict(validation)
        validation["status"] = "partial"
        validation["message"] = (
            "Kabupaten/provinsi cocok, tetapi desa/kecamatan belum dapat "
            "dikonfirmasi. Fallback diblokir."
        )
        return False, validation

    return True, validation


def geocode_npsn_fallback(
    npsn,
    nama_sekolah,
    alamat,
    desa,
    kecamatan,
    kabupaten_kota,
    provinsi,
    google_api_key="",
):
    """Cari titik cadangan HANYA ketika koordinat resmi NPSN = 0,0.

    V8.7 memakai beberapa jalur yang benar-benar independen:
    1) Google Places (New) untuk mencari POI sekolah berdasarkan nama + wilayah.
    2) OpenStreetMap/Nominatim untuk mencari POI sekolah/alamat secara terpisah.
    3) Google Geocoding untuk mengonfirmasi alamat resmi dan presisi geocode.

    Google Places TIDAK lagi menunggu OSM berhasil terlebih dahulu.
    """
    school_name = _collapse_spaces(nama_sekolah)
    address = _collapse_spaces(alamat)
    region_tail = ", ".join(
        part for part in [desa, kecamatan, kabupaten_kota, provinsi, "Indonesia"] if part
    )

    if not school_name:
        raise ValueError(
            "Nama satuan pendidikan tidak tersedia pada data resmi; fallback geocoding diblokir."
        )

    query_specs = [
        (
            "nama+npsn+wilayah",
            ", ".join(part for part in [school_name, f"NPSN {npsn}", region_tail] if part),
        ),
        (
            "nama+alamat",
            ", ".join(part for part in [school_name, address, region_tail] if part),
        ),
        (
            "nama+wilayah",
            ", ".join(part for part in [school_name, region_tail] if part),
        ),
        (
            "nama+lokal",
            ", ".join(
                part for part in [school_name, desa, kecamatan, kabupaten_kota, provinsi] if part
            ),
        ),
    ]
    if address:
        query_specs.append(
            (
                "alamat+wilayah",
                ", ".join(part for part in [address, region_tail] if part),
            )
        )

    # --------------------------------------------------------
    # A. GOOGLE PLACES (INDEPENDEN, boleh sukses walau OSM gagal)
    # --------------------------------------------------------
    google_places_candidates, google_places_errors = _build_google_places_candidates(
        query_specs,
        school_name,
        desa,
        kecamatan,
        kabupaten_kota,
        provinsi,
        google_api_key,
    )

    # --------------------------------------------------------
    # B. OPENSTREETMAP / NOMINATIM (INDEPENDEN)
    # --------------------------------------------------------
    osm_candidates = []
    osm_search_errors = []

    for query_id, query in query_specs:
        try:
            results = _nominatim_search(query)
        except Exception as exc:
            osm_search_errors.append(f"{query_id}: {exc}")
            continue

        for item in results:
            try:
                lat = float(item.get("lat"))
                lon = float(item.get("lon"))
            except (TypeError, ValueError):
                continue

            namedetails = item.get("namedetails") or {}
            candidate_name = (
                item.get("name")
                or namedetails.get("name")
                or namedetails.get("name:id")
                or _collapse_spaces(item.get("display_name", "")).split(",")[0]
            )
            name_similarity = _school_name_similarity(school_name, candidate_name)

            category = str(item.get("category") or item.get("class") or "").lower()
            item_type = str(item.get("type") or "").lower()
            school_like = (
                category in {"amenity", "education"}
                and item_type in {
                    "school", "kindergarten", "childcare", "college", "university", "training"
                }
            ) or item_type in {"school", "kindergarten", "childcare"}

            strict_ok, validation = _fallback_candidate_is_strictly_valid(
                lat,
                lon,
                desa,
                kecamatan,
                kabupaten_kota,
                provinsi,
            )
            if not strict_ok:
                continue

            min_similarity = 0.68 if school_like else 0.88
            if name_similarity < min_similarity:
                continue

            osm_candidates.append(
                {
                    "provider": "OpenStreetMap/Nominatim",
                    "query_id": query_id,
                    "query_ids": {query_id},
                    "query": query,
                    "latitude": lat,
                    "longitude": lon,
                    "candidate_name": _collapse_spaces(candidate_name),
                    "display_name": _collapse_spaces(item.get("display_name", "")),
                    "name_similarity": name_similarity,
                    "school_like": school_like,
                    "validation": validation,
                    "score": name_similarity + (0.10 if school_like else 0.0),
                }
            )

    # Gabungkan query OSM yang mengarah ke titik hampir sama agar ada consensus.
    for candidate in osm_candidates:
        for other in osm_candidates:
            if other is candidate:
                continue
            if _distance_meters(
                candidate["latitude"], candidate["longitude"],
                other["latitude"], other["longitude"],
            ) <= 150:
                candidate["query_ids"].add(other["query_id"])

    osm_candidates.sort(
        key=lambda c: (len(c.get("query_ids") or []), c.get("score", 0)),
        reverse=True,
    )

    # --------------------------------------------------------
    # C. GOOGLE GEOCODING (SUPPORTING EVIDENCE, bukan POI tunggal)
    # --------------------------------------------------------
    google_geocode_candidates = []
    google_geocode_errors = []
    if _google_api_key_is_configured(google_api_key):
        geocode_queries = []
        if address:
            geocode_queries.append(
                ("alamat_resmi", ", ".join(part for part in [address, region_tail] if part))
            )
        geocode_queries.append(
            ("nama_alamat", ", ".join(part for part in [school_name, address, region_tail] if part))
        )

        for query_id, query in geocode_queries:
            try:
                results = _google_geocode_candidates(query, google_api_key)
            except Exception as exc:
                google_geocode_errors.append(f"{query_id}: {exc}")
                continue
            for result in results[:5]:
                region_validation = _google_region_validation(
                    result.get("formatted_address", ""),
                    result.get("address_components") or [],
                    desa,
                    kecamatan,
                    kabupaten_kota,
                    provinsi,
                )
                if region_validation.get("status") != "verified":
                    continue
                result.update(
                    {
                        "provider": "Google Geocoding",
                        "query_id": query_id,
                        "query": query,
                        "validation": region_validation,
                    }
                )
                google_geocode_candidates.append(result)

    google_geocode_consensus = _merge_google_geocode_consensus(
        google_geocode_candidates,
        radius_meters=120,
    )

    # --------------------------------------------------------
    # D. PILIH TITIK BERDASARKAN BUKTI TERKUAT
    # --------------------------------------------------------
    chosen = None
    confidence = None
    provider_note = None
    cross_provider_distance = None

    best_google = google_places_candidates[0] if google_places_candidates else None
    best_osm = osm_candidates[0] if osm_candidates else None
    best_geocode = google_geocode_consensus[0] if google_geocode_consensus else None

    # 1) Bukti terbaik: Google POI sekolah + OSM sekolah berdekatan.
    if best_google and best_osm:
        distance = _distance_meters(
            best_google["latitude"], best_google["longitude"],
            best_osm["latitude"], best_osm["longitude"],
        )
        if distance <= 200:
            chosen = best_google
            confidence = "VERY HIGH"
            provider_note = "Google Places + OpenStreetMap cross-provider consensus"
            cross_provider_distance = distance

    # 2) Google Places sendiri boleh menjadi sumber utama jika POI-nya kuat dan
    #    muncul konsisten dari >=2 query berbeda.
    if chosen is None and best_google:
        google_query_count = len(best_google.get("query_ids") or [])
        if (
            best_google.get("school_like")
            and best_google.get("name_similarity", 0) >= 0.78
            and google_query_count >= 2
        ):
            chosen = best_google
            confidence = "HIGH"
            provider_note = "Google Places (New) multi-query POI consensus"

    # 3) Satu Google POI juga boleh lolos bila namanya sangat kuat (>=90%) dan
    #    wilayah sampai level lokal cocok. Ini menangani sekolah yang memang
    #    belum terpetakan di OSM.
    if chosen is None and best_google:
        validation = best_google.get("validation") or {}
        if (
            best_google.get("school_like")
            and best_google.get("name_similarity", 0) >= 0.90
            and validation.get("status") == "verified"
        ):
            chosen = best_google
            confidence = "HIGH"
            provider_note = "Google Places (New) exact/strong POI match"

    # 4) OSM tetap boleh menjadi sumber bila ada consensus multi-query internal.
    if chosen is None and best_osm:
        osm_query_count = len(best_osm.get("query_ids") or [])
        if osm_query_count >= 2:
            chosen = best_osm
            confidence = "HIGH"
            provider_note = "OpenStreetMap/Nominatim multi-query consensus"

    # 5) Google Places + Google Geocoding boleh lolos walau OSM tidak punya POI,
    #    asalkan kedua provider berdekatan dan geocode cukup presisi.
    if chosen is None and best_google and best_geocode:
        geocode_distance = _distance_meters(
            best_google["latitude"], best_google["longitude"],
            best_geocode["latitude"], best_geocode["longitude"],
        )
        if (
            geocode_distance <= 150
            and _google_geocode_is_high_precision(best_geocode)
            and best_google.get("validation", {}).get("status") == "verified"
            and best_geocode.get("validation", {}).get("status") == "verified"
        ):
            chosen = best_google
            confidence = "VERY HIGH"
            provider_note = "Google Places + Google Geocoding consensus"
            chosen["google_geocode_confirmation"] = {
                "distance_m": geocode_distance,
                "formatted_address": best_geocode.get("formatted_address", ""),
                "location_type": best_geocode.get("location_type", ""),
            }

    # 6) Google Geocoding sendiri boleh menjadi fallback hanya jika minimal
    #    dua query independen konvergen <=120 m, wilayah resmi VERIFIED,
    #    dan hasilnya high precision (ROOFTOP/premise/establishment/POI).
    if chosen is None and best_geocode:
        geocode_query_count = len({q for q in best_geocode.get("query_ids", set()) if q})
        if (
            geocode_query_count >= 2
            and _google_geocode_is_high_precision(best_geocode)
            and best_geocode.get("validation", {}).get("status") == "verified"
        ):
            chosen = best_geocode
            confidence = "HIGH"
            provider_note = "Google Geocoding multi-query high-precision consensus"

    # 7) Setelah kandidat utama ada, Google Geocoding juga dipakai sebagai
    #    konfirmasi alamat untuk memperkuat confidence.
    if chosen is not None and google_geocode_candidates:
        confirmation_pool = [
            g for g in google_geocode_candidates
            if not (
                chosen.get("provider") == "Google Geocoding"
                and abs(g["latitude"] - chosen["latitude"]) < 1e-12
                and abs(g["longitude"] - chosen["longitude"]) < 1e-12
            )
        ]
        if not confirmation_pool:
            confirmation_pool = google_geocode_candidates
        nearest = min(
            confirmation_pool,
            key=lambda g: _distance_meters(
                chosen["latitude"], chosen["longitude"],
                g["latitude"], g["longitude"],
            ),
        )
        geocode_distance = _distance_meters(
            chosen["latitude"], chosen["longitude"],
            nearest["latitude"], nearest["longitude"],
        )
        if geocode_distance <= 250:
            chosen["google_geocode_confirmation"] = {
                "distance_m": geocode_distance,
                "formatted_address": nearest.get("formatted_address", ""),
                "location_type": nearest.get("location_type", ""),
            }
            if confidence == "HIGH":
                confidence = "VERY HIGH"
                provider_note += " + Google Geocoding address confirmation"

    if chosen is None:
        google_key_ready = _google_api_key_is_configured(google_api_key)
        diagnostics = []
        diagnostics.append(f"Google Places kandidat valid: {len(google_places_candidates)}")
        diagnostics.append(f"OSM kandidat valid: {len(osm_candidates)}")
        diagnostics.append(f"Google Geocoding kandidat valid: {len(google_geocode_candidates)}")
        diagnostics.append(f"Google Geocoding consensus cluster: {len(google_geocode_consensus)}")

        if not google_key_ready:
            hint = (
                " Untuk kasus sekolah yang belum ada di OpenStreetMap, tambahkan GOOGLE_MAPS_API_KEY "
                "di Streamlit Secrets dan aktifkan Places API (New) + Geocoding API pada Google Cloud."
            )
        else:
            hint = (
                " Google API sudah terdeteksi, tetapi belum ada POI/alamat yang memenuhi semua validasi "
                "nama + desa/kecamatan + kabupaten/kota + provinsi."
            )

        error_details = []
        if google_places_errors:
            gp_detail = "; ".join(google_places_errors[:2])
            if "API_KEY_SERVICE_BLOCKED" in gp_detail or "PERMISSION_DENIED" in gp_detail:
                gp_detail += " [Aktifkan Places API (New) dan izinkan API tersebut pada API restrictions key.]"
            error_details.append("Google Places: " + gp_detail)
        if osm_search_errors:
            error_details.append("OSM: " + "; ".join(osm_search_errors[:2]))
        if google_geocode_errors:
            gg_detail = "; ".join(google_geocode_errors[:2])
            if "REQUEST_DENIED" in gg_detail or "not authorized" in gg_detail.lower():
                gg_detail += " [Aktifkan Geocoding API dan izinkan Geocoding API pada API restrictions key.]"
            error_details.append("Google Geocoding: " + gg_detail)
        detail_text = (" Detail teknis: " + " | ".join(error_details)) if error_details else ""

        raise ValueError(
            "Fallback belum menemukan titik sekolah dengan bukti yang cukup kuat. "
            + " | ".join(diagnostics)
            + "."
            + hint
            + detail_text
        )

    # --------------------------------------------------------
    # E. VALIDASI FINAL: kalau kandidat Google, gunakan validasi Google.
    #    Kalau kandidat OSM, gunakan validasi OSM. Jangan memaksa OSM reverse
    #    terhadap kandidat Google karena tujuan V8.7 adalah provider independen.
    # --------------------------------------------------------
    validation = chosen.get("validation") or {}
    if validation.get("status") != "verified":
        raise ValueError(
            "Kandidat ditemukan tetapi validasi wilayah final belum VERIFIED. Generate diblokir."
        )

    return {
        "latitude": chosen["latitude"],
        "longitude": chosen["longitude"],
        "validation": validation,
        "confidence": confidence or "HIGH",
        "provider_note": provider_note or chosen.get("provider", "Fallback tervalidasi"),
        "candidate_name": chosen.get("candidate_name", ""),
        "display_name": chosen.get("display_name", ""),
        "name_similarity": chosen.get("name_similarity", 0.0),
        "consensus_count": len(chosen.get("query_ids") or []),
        "cross_provider_distance_m": cross_provider_distance,
        "google_confirmation": chosen.get("google_geocode_confirmation"),
        "provider": chosen.get("provider", ""),
        "npsn": npsn,
    }


# ============================================================
# CACHE + ORKESTRASI LOOKUP
# ============================================================

CACHE_TTL_SECONDS = 21600


class _ValidatorUnavailable(Exception):
    """Dilempar agar hasil 'unavailable' TIDAK masuk cache (exception tidak di-cache)."""


def _reverse_validate_or_raise(*args):
    result = reverse_validate_location(*args)
    if result.get("status") == "unavailable":
        raise _ValidatorUnavailable(result)
    return result


def _identity_cache(func):
    return func


_cache = st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False) if st is not None else _identity_cache

lookup_npsn_online_cached = _cache(lookup_npsn_online)
geocode_npsn_fallback_cached = _cache(geocode_npsn_fallback)
_reverse_validate_cached = _cache(_reverse_validate_or_raise)


def reverse_validate_location_cached(*args):
    """Seperti reverse_validate_location, di-cache 6 jam, tetapi kegagalan sementara
    Nominatim (timeout/429) tidak ikut tersimpan -> bisa langsung dicoba ulang."""
    try:
        return _reverse_validate_cached(*args)
    except _ValidatorUnavailable as unavailable:
        return unavailable.args[0]


def resolve_npsn(npsn, fallback_enabled=False, google_api_key=""):
    """Alur lengkap: data resmi -> validasi reverse-geocoding (atau fallback bila 0,0).

    Logika cabang identik dengan versi sebelumnya; hanya dipindah dari UI ke sini.
    """
    info = lookup_npsn_online_cached(npsn)
    info["fallback_enabled_at_lookup"] = bool(fallback_enabled)

    if info.get("official_coordinate_valid"):
        info["validation"] = reverse_validate_location_cached(
            info["latitude"], info["longitude"],
            info["desa"], info["kecamatan"], info["kabupaten_kota"], info["provinsi"],
        )
        info["coordinate_source_type"] = "official"
        info["source_name"] = "Referensi Data Kemendikdasmen (koordinat resmi)"

    elif fallback_enabled:
        fallback = geocode_npsn_fallback_cached(
            info["npsn"], info.get("nama_sekolah", ""), info.get("alamat", ""),
            info.get("desa", ""), info.get("kecamatan", ""),
            info.get("kabupaten_kota", ""), info.get("provinsi", ""),
            google_api_key,
        )
        info["latitude"] = fallback["latitude"]
        info["longitude"] = fallback["longitude"]
        info["validation"] = fallback["validation"]
        info["coordinate_source_type"] = "fallback"
        info["source_name"] = fallback.get("provider_note", "Fallback geocoding tervalidasi")
        info["fallback"] = fallback

    else:
        info["validation"] = {
            "status": "official_missing",
            "message": (
                "Koordinat resmi NPSN masih 0,0. Fallback belum diaktifkan, "
                "jadi Generate tetap diblokir."
            ),
        }
        info["coordinate_source_type"] = "official_missing"

    return info
