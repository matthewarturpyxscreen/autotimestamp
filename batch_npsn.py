import io
import math
import difflib
import os
import re
import secrets
import threading
import time as _pyx_clock
import zipfile
from pyx_batch_archive import new_archive, download_data, close_result
from pyx_image_job_guard import image_job_slot, ImageServerBusy
from datetime import datetime, date, time, timedelta
from urllib.parse import quote

import cv2
import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
from workspace_preview import batch_gallery, compact_preview, input_signature, output_is_stale, preview_locked_size, read_image_dimensions

try:
    import streamlit as st
except ImportError:  # hanya untuk test helper di environment tanpa Streamlit
    st = None


# ============================================================
# ONLINE NPSN CONFIG
# ============================================================

KEMENDIKDASMEN_NPSN_URL = (
    "https://referensi.data.kemendikdasmen.go.id/satpen/detail/{npsn}"
)
# Cadangan tetap dari domain RESMI Kemendikdasmen, bukan hasil pencarian peta.
# Digunakan HANYA bila titik pada detail utama memang 0,0.
KEMENDIKDASMEN_OFFICIAL_ALTERNATES = (
    "https://referensi.data.kemendikdasmen.go.id/pendidikan/npsn/{npsn}",
    "https://referensi.data.kemendikdasmen.go.id/tabs.php?npsn={npsn}",
)
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
GOOGLE_PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
HTTP_TIMEOUT_SECONDS = 15
# Versi terlihat di halaman untuk memastikan deploy GitHub/Streamlit benar.
NPSN_VALIDATOR_BUILD = "V9.5.2.4.26 · Official Recovery + OSM ECO"
HTTP_HEADERS = {
    "User-Agent": "AutoTimestamp-NPSN/8.8 (Streamlit; NPSN location lookup)",
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
# TIMEZONE HELPERS
# ============================================================


def _timezone_options():
    return [
        "WIB", "WITA", "WIT", "GMT", "UTC",
        "GMT-12", "GMT-11", "GMT-10", "GMT-9", "GMT-8", "GMT-7", "GMT-6",
        "GMT-5", "GMT-4", "GMT-3", "GMT-2", "GMT-1", "GMT+0", "GMT+1", "GMT+2",
        "GMT+3", "GMT+4", "GMT+5", "GMT+6", "GMT+7", "GMT+8", "GMT+9", "GMT+10",
        "GMT+11", "GMT+12", "GMT+13", "GMT+14",
        "UTC-12", "UTC-11", "UTC-10", "UTC-9", "UTC-8", "UTC-7", "UTC-6",
        "UTC-5", "UTC-4", "UTC-3", "UTC-2", "UTC-1", "UTC+0", "UTC+1", "UTC+2",
        "UTC+3", "UTC+4", "UTC+5", "UTC+6", "UTC+7", "UTC+8", "UTC+9", "UTC+10",
        "UTC+11", "UTC+12", "UTC+13", "UTC+14",
    ]


def _normalize_province_for_timezone(value):
    value = _collapse_spaces(value).lower()
    value = value.replace("d.k.i.", "dki").replace("d.i.", "di")
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    for prefix in ["provinsi ", "propinsi ", "prov "]:
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
    aliases = {
        "daerah khusus ibukota jakarta": "dki jakarta",
        "daerah khusus jakarta": "dki jakarta",
        "jakarta": "dki jakarta",
        "daerah istimewa yogyakarta": "di yogyakarta",
        "yogyakarta": "di yogyakarta",
    }
    return aliases.get(value, value)


def _infer_indonesia_timezone_from_province(province):
    p = _normalize_province_for_timezone(province)
    if not p:
        return None

    wib = {
        "aceh", "sumatera utara", "sumatera barat", "riau", "kepulauan riau",
        "jambi", "bengkulu", "sumatera selatan", "kepulauan bangka belitung",
        "lampung", "banten", "dki jakarta", "jawa barat", "jawa tengah",
        "di yogyakarta", "jawa timur", "kalimantan barat", "kalimantan tengah",
    }
    wita = {
        "bali", "nusa tenggara barat", "nusa tenggara timur",
        "kalimantan selatan", "kalimantan timur", "kalimantan utara",
        "sulawesi utara", "gorontalo", "sulawesi tengah", "sulawesi barat",
        "sulawesi selatan", "sulawesi tenggara",
    }
    wit = {
        "maluku", "maluku utara", "papua", "papua barat", "papua barat daya",
        "papua tengah", "papua pegunungan", "papua selatan",
    }

    if p in wib:
        return {"indonesia_label": "WIB", "gmt_label": "GMT+7", "utc_label": "UTC+7", "offset": 7}
    if p in wita:
        return {"indonesia_label": "WITA", "gmt_label": "GMT+8", "utc_label": "UTC+8", "offset": 8}
    if p in wit:
        return {"indonesia_label": "WIT", "gmt_label": "GMT+9", "utc_label": "UTC+9", "offset": 9}
    return None


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


def _official_url_allowlist(npsn):
    safe_npsn = quote(npsn, safe="")
    return {KEMENDIKDASMEN_NPSN_URL.format(npsn=safe_npsn)} | {
        template.format(npsn=safe_npsn)
        for template in KEMENDIKDASMEN_OFFICIAL_ALTERNATES
    }


def _recover_missing_official_point(primary):
    """Read alternate *official* pages only for verified same-school 0,0 records.

    Both pages must carry the exact requested NPSN, the same school name,
    kabupaten and province. Never substitute external map coordinates here.
    Missing/404/timeout pages are ignored without affecting the primary identity.
    """
    if primary.get("official_coordinate_valid"):
        return primary
    npsn = primary["npsn"]
    for url_template in KEMENDIKDASMEN_OFFICIAL_ALTERNATES:
        source_url = url_template.format(npsn=quote(npsn, safe=""))
        try:
            resp = requests.get(source_url, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT_SECONDS)
            if resp.status_code != 200:
                continue
            alt = _parse_kemendikdasmen_npsn_html(resp.text, npsn, source_url)
        except (requests.RequestException, ValueError, TypeError):
            continue
        if not alt.get("official_coordinate_valid"):
            continue
        primary_name = _normalize_school_name(primary.get("nama_sekolah"))
        alt_name = _normalize_school_name(alt.get("nama_sekolah"))
        if not primary_name or not alt_name or primary_name != alt_name:
            continue
        if not all(_region_matches(primary.get(field), alt.get(field)) is True
                   for field in ("kabupaten_kota", "provinsi")):
            continue
        # Only official data replaces the official coordinate. Keep the official
        # source URL accurate and expose exactly which endpoint supplied it.
        primary = dict(primary)
        for key in ("latitude", "longitude", "official_latitude", "official_longitude",
                    "official_coordinate_valid", "coordinate_source_type", "source_url"):
            primary[key] = alt[key]
        primary["coordinate_recovery"] = "Titik dipulihkan dari halaman alternatif resmi Kemendikdasmen"
        return primary
    return primary


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

    primary = _parse_kemendikdasmen_npsn_html(
        response.text,
        requested_npsn=npsn,
        source_url=source_url,
    )
    return _recover_missing_official_point(primary)


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
# RESILIENT SECONDARY VALIDATOR FOR OFFICIAL NPSN COORDINATES
# Only invoked when Nominatim is unavailable. Never turns a
# mismatch or incomplete evidence into a verified coordinate.
# ============================================================

WILAYAH_ID_REVERSE_URL = (
    "https://wilayah-id-api.dhanypedia.com/api/v1/boundaries/reverse"
)


def _extract_region_name(value):
    if isinstance(value, str):
        return _collapse_spaces(value)
    if not isinstance(value, dict):
        return ""
    for field in ("name", "nama", "nama_wilayah", "region_name", "namobj", "label"):
        item = value.get(field)
        if isinstance(item, dict):
            for key in ("local", "id", "long_name"):
                if isinstance(item.get(key), str):
                    return _collapse_spaces(item[key])
        if isinstance(item, str):
            return _collapse_spaces(item)
    return ""


def _verified_external_region_result(provider, kab, prov, official_kab, official_prov, *,
                                     kec="", desa="", note=""):
    # Verifikasi wajib kabupaten + provinsi dengan value dari respons penyedia,
    # bukan dari NPSN yang dipakai sebagai input.
    kab_match = _region_matches(official_kab, kab)
    prov_match = _region_matches(official_prov, prov)
    verified = kab_match is True and prov_match is True
    explicit_mismatch = kab_match is False or prov_match is False
    status = "verified" if verified else ("mismatch" if explicit_mismatch else "partial")
    return {
        "status": status,
        "message": (
            f"Kabupaten/kota dan provinsi cocok menurut {provider}."
            if verified else (
                f"{provider} menemukan wilayah berbeda dari data NPSN: {kab or '-'}, {prov or '-'}."
                if explicit_mismatch else
                f"{provider} belum bisa memastikan kabupaten/kota dan provinsi."
            )
        ),
        "provider": provider,
        "reverse_desa": desa,
        "reverse_kecamatan": kec,
        "reverse_kabupaten": kab,
        "reverse_provinsi": prov,
        "display_name": note,
        "desa_match": _region_matches("", desa),
        "kec_match": _region_matches("", kec),
        "kab_match": kab_match,
        "prov_match": prov_match,
    }



def _wilayah_reverse_record(payload, expected_level=None):
    """Read region names from a wilayah-id reverse response, without guessing parents.

    API responses may contain a complete hierarchy OR only the requested level.
    A standalone village's `name` is never mistaken for a regency/province.
    """
    if not isinstance(payload, dict) or payload.get("success") is False:
        raise ValueError("Respons wilayah tidak valid")
    raw = payload.get("data")
    if isinstance(raw, list):
        if len(raw) != 1:
            raise ValueError("Respons wilayah kosong atau ambigu")
        raw = raw[0]
    if not isinstance(raw, dict):
        raise ValueError("Validator wilayah tidak mengembalikan data wilayah")

    parts = [raw]
    for parent in ("regions", "hierarchy", "administrative", "result", "properties", "region"):
        container = raw.get(parent)
        if isinstance(container, dict):
            parts.append(container)
    kab = prov = kec = desa = ""
    for part in parts:
        for keys, target in (
            (("regency", "kabupaten", "kabupaten_kota", "city", "district_city",
              "regency_name", "kabupaten_nama", "nama_kabupaten", "name_regency"), "kab"),
            (("province", "provinsi", "province_name", "provinsi_nama",
              "nama_provinsi", "name_province"), "prov"),
            (("district", "kecamatan", "district_name", "nama_kecamatan"), "kec"),
            (("village", "desa", "village_name", "nama_desa"), "desa"),
        ):
            candidate = ""
            for key in keys:
                candidate = _extract_region_name(part.get(key))
                if candidate:
                    break
            if target == "kab" and not kab:
                kab = candidate
            elif target == "prov" and not prov:
                prov = candidate
            elif target == "kec" and not kec:
                kec = candidate
            elif target == "desa" and not desa:
                desa = candidate

        # A `name` field refers to one specific administrative level,
        # unlike parent fields above. Use explicit `level` when supplied.
        declared_level = str(part.get("level") or part.get("type") or "").lower().strip()
        level_labels = {
            "provinces": "provinces", "province": "provinces", "provinsi": "provinces",
            "regencies": "regencies", "regency": "regencies", "kabupaten": "regencies", "kabupaten_kota": "regencies",
            "districts": "districts", "district": "districts", "kecamatan": "districts",
            "villages": "villages", "village": "villages", "desa": "villages",
        }
        actual_level = level_labels.get(declared_level)
        if expected_level and actual_level and actual_level != expected_level:
            raise ValueError("API mengembalikan level wilayah berbeda dari yang diminta")
        chosen_level = actual_level or expected_level
        name = _extract_region_name(part)
        if name:
            if chosen_level == "regencies" and not kab:
                kab = name
            elif chosen_level == "provinces" and not prov:
                prov = name
            elif chosen_level == "districts" and not kec:
                kec = name
            elif chosen_level == "villages" and not desa:
                desa = name
    return {"kab": kab, "prov": prov, "kec": kec, "desa": desa,
            "regency_code": str(raw.get("regency_code") or "").strip(),
            "province_code": str(raw.get("province_code") or "").strip(),
            "code": str(raw.get("code") or "").strip()}


def _wilayah_id_validate(latitude, longitude, official_kab, official_prov):
    """Validate official NPSN point with wilayah-id, including single-level results.

    Request at most three levels (default + explicitly missing regency/province).
    An explicit result from `level=regencies` and `level=provinces` is a
    coordinate-based lookup, not an inferred address from NPSN text.
    """
    params = {"lat": f"{latitude:.8f}", "lng": f"{longitude:.8f}"}
    headers = {"Accept": "application/json", "User-Agent": HTTP_HEADERS["User-Agent"]}

    def request(level=None):
        query = {**params, **({"level": level} if level else {})}
        resp = requests.get(WILAYAH_ID_REVERSE_URL,
                            params=query, headers=headers, timeout=6)
        if resp.status_code != 200:
            raise requests.RequestException(f"HTTP {resp.status_code}")
        return _wilayah_reverse_record(resp.json(), expected_level=level)

    found = request()
    # Default reverse often returns only a village/district record. Do not
    # assume such a record contains province/regency when absent.
    if not found["kab"]:
        regency = request("regencies")
        found["kab"] = regency["kab"]
        # Parent province is acceptable only when explicitly returned.
        found["prov"] = found["prov"] or regency["prov"]
        found["regency_code"] = found["regency_code"] or regency["code"]
        found["province_code"] = found["province_code"] or regency["province_code"]
    if not found["prov"]:
        province = request("provinces")
        found["prov"] = province["prov"]
        if found["province_code"] and province["code"] and found["province_code"] != province["code"]:
            raise ValueError("Kode hierarki kabupaten/provinsi bertentangan")
    if not found["kab"] or not found["prov"]:
        raise ValueError("Kabupaten/provinsi tidak ditemukan pada lookup koordinat per level")
    return _verified_external_region_result(
        "Wilayah Indonesia (BIG)", found["kab"], found["prov"], official_kab,
        official_prov, kec=found["kec"], desa=found["desa"],
    )


def _google_reverse_validate_official(latitude, longitude, official_kab, official_prov, api_key):
    if not _google_api_key_is_configured(api_key):
        raise ValueError("GOOGLE_MAPS_API_KEY belum disetel")
    response = requests.get(
        GOOGLE_GEOCODE_URL,
        params={"latlng": f"{latitude:.8f},{longitude:.8f}", "language": "id", "key": api_key},
        timeout=8,
    )
    if response.status_code != 200:
        raise requests.RequestException(f"Google HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("status") != "OK":
        raise ValueError(f"Google status {payload.get('status', 'UNKNOWN') if isinstance(payload, dict) else 'UNKNOWN'}")
    # Satu hasil Google yang memuat kedua level administratif secara eksplisit.
    # Jangan membuat pasangan provinsi/kabupaten dari hasil berbeda.
    for item in (payload.get("results") or [])[:12]:
        by_type = {}
        for comp in item.get("address_components") or []:
            for kind in comp.get("types") or []:
                by_type.setdefault(kind, _collapse_spaces(comp.get("long_name", "")))
        country = _collapse_spaces(by_type.get("country", "")).lower()
        if country and country not in {"indonesia", "id"}:
            continue
        kab = by_type.get("administrative_area_level_2", "")
        prov = by_type.get("administrative_area_level_1", "")
        if not kab or not prov:
            continue
        result = _verified_external_region_result(
            "Google Geocoding", kab, prov, official_kab, official_prov,
            kec=by_type.get("administrative_area_level_3", ""),
            note=_collapse_spaces(item.get("formatted_address", "")),
        )
        if result["status"] == "verified":
            return result
    raise ValueError("Tidak ada satu hasil Google dengan kabupaten dan provinsi cocok")


def _safe_validator_diagnostic(message, api_key=""):
    """Prevent API keys from leaking into Streamlit UI/log diagnostics."""
    value = str(message or "")
    if api_key:
        value = value.replace(str(api_key), "[redacted]")
    value = re.sub(r"(?i)(?<=key=)[^&\s]+", "[redacted]", value)
    value = re.sub(r"(?i)(?<=api_key=)[^&\s]+", "[redacted]", value)
    return value[:140]


def _official_npsn_coordinate_ready(info):
    """Can generate from an unchanged, valid official Kemendikdasmen NPSN point.

    This verifies the trusted NPSN lookup provenance/coordinate integrity,
    NOT the geographical accuracy of the ministry's published position.
    Reverse-geocoding is supplemental and cannot override an intact official
    point. Never applies to user-supplied/fallback or 0,0 coordinates.
    """
    if not isinstance(info, dict):
        return False
    if info.get("coordinate_source_type") != "official":
        return False
    if info.get("official_coordinate_valid") is not True:
        return False
    npsn = _normalize_npsn(info.get("npsn"))
    if not re.fullmatch(r"[A-Z0-9]{8}", npsn):
        return False
    if str(info.get("source_url", "")) not in _official_url_allowlist(npsn):
        return False
    if not _collapse_spaces(info.get("kabupaten_kota")) or not _collapse_spaces(info.get("provinsi")):
        return False
    try:
        latitude = float(info.get("latitude"))
        longitude = float(info.get("longitude"))
        official_lat = float(info.get("official_latitude"))
        official_lon = float(info.get("official_longitude"))
    except (TypeError, ValueError, OverflowError):
        return False
    if not all(math.isfinite(x) for x in (latitude, longitude, official_lat, official_lon)):
        return False
    if not (-11.5 <= latitude <= 6.5 and 94 <= longitude <= 142.5):
        return False
    if abs(latitude) < 1e-12 and abs(longitude) < 1e-12:
        return False
    return (
        math.isclose(latitude, official_lat, rel_tol=0, abs_tol=1e-9)
        and math.isclose(longitude, official_lon, rel_tol=0, abs_tol=1e-9)
    )


def _npsn_generation_authorized(info):
    """Official NPSN is authoritative; only fallback requires map verified."""
    if not isinstance(info, dict):
        return False
    if info.get("coordinate_source_type") == "official":
        return _official_npsn_coordinate_ready(info)
    if info.get("coordinate_source_type") == "fallback":
        return (info.get("validation") or {}).get("status") == "verified"
    return False


def _official_manual_review_allowed(info, validation):
    """Legacy manual review rule; only for genuine official-source map outages."""
    return (
        isinstance(validation, dict)
        and validation.get("status") == "unavailable"
        and _official_npsn_coordinate_ready(info)
    )


def _resolve_unavailable_official_validation(primary_result, latitude, longitude,
                                              official_kab, official_prov, google_api_key=""):
    # An incomplete Nominatim response is also insufficient evidence. Try
    # authoritative coordinate-based boundaries instead of getting stuck for
    # six hours on a partial cache result. Known mismatches are NEVER bypassed.
    if primary_result.get("status") not in {"unavailable", "partial"}:
        return primary_result
    causes = []
    for label, getter in (
        ("Wilayah Indonesia", lambda: _wilayah_id_validate(latitude, longitude, official_kab, official_prov)),
        ("Google", lambda: _google_reverse_validate_official(latitude, longitude, official_kab, official_prov, google_api_key)),
    ):
        if label == "Google" and not _google_api_key_is_configured(google_api_key):
            causes.append("Google: API key belum dikonfigurasi")
            continue
        try:
            outcome = getter()
            if outcome.get("status") in {"verified", "mismatch"}:
                # Mismatch by a coordinate-based boundary lookup is stronger
                # evidence than an unavailable provider. Do not convert it to
                # 'unavailable' and accidentally offer manual-review bypass.
                outcome["primary_error"] = _collapse_spaces(primary_result.get("error", ""))[:120]
                return outcome
            causes.append(f"{label}: hierarki wilayah kurang lengkap")
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            causes.append(f"{label}: {_safe_validator_diagnostic(exc, google_api_key)}")
    blocked = dict(primary_result)
    blocked["fallback_diagnostics"] = "; ".join(causes)
    blocked["message"] = (
        "Pemeriksaan wilayah otomatis belum menghasilkan kecocokan kabupaten dan provinsi. "
        "Generate tetap diblokir hingga berhasil diverifikasi atau dikonfirmasi manual "
        "(hanya untuk titik resmi dengan status layanan tidak tersedia)."
    )
    return blocked


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


# Shared across concurrent Streamlit sessions in this Python worker.
# Nominatim public policy: <=1 request/second for ALL app sessions, cached.
_OSM_LOCK = threading.RLock()
_OSM_LAST_REQUEST = 0.0
_OSM_COOLDOWN_UNTIL = 0.0
_OSM_SEARCH_CACHE = {}  # query -> (expiry_monotonic, result)
_OSM_MIN_GAP_SECONDS = 1.1
_OSM_429_BACKOFF_SECONDS = 600.0


class _OSMTemporarilyLimited(requests.RequestException):
    """Don't retry a rate-limited public Nominatim service immediately."""


def _nominatim_search(query):
    global _OSM_LAST_REQUEST, _OSM_COOLDOWN_UNTIL
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
    cache_key = _collapse_spaces(query).casefold()
    with _OSM_LOCK:
        now = _pyx_clock.monotonic()
        cached = _OSM_SEARCH_CACHE.get(cache_key)
        if cached and cached[0] > now:
            return list(cached[1])
        if now < _OSM_COOLDOWN_UNTIL:
            raise _OSMTemporarilyLimited("Nominatim dibatasi (HTTP 429); tunggu cooldown, jangan ulangi pencarian dulu")
        pause = _OSM_MIN_GAP_SECONDS - (now - _OSM_LAST_REQUEST)
        if pause > 0 and _OSM_LAST_REQUEST:
            _pyx_clock.sleep(pause)
        _OSM_LAST_REQUEST = _pyx_clock.monotonic()
        response = requests.get(
            NOMINATIM_SEARCH_URL,
            params=params,
            headers=HTTP_HEADERS,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code in (429, 403):
            # Respect provider throttling; don't flood with query variants.
            retry_after = (getattr(response, "headers", None) or {}).get("Retry-After", "")
            try:
                cooldown = max(_OSM_429_BACKOFF_SECONDS, min(3600.0, float(retry_after)))
            except (TypeError, ValueError):
                cooldown = _OSM_429_BACKOFF_SECONDS
            _OSM_COOLDOWN_UNTIL = _pyx_clock.monotonic() + cooldown
            raise _OSMTemporarilyLimited(f"Nominatim search HTTP {response.status_code}; cooldown aktif")
        if response.status_code != 200:
            raise requests.RequestException(f"Nominatim search HTTP {response.status_code}")
        payload = response.json()
        result = payload if isinstance(payload, list) else []
        # Cache only successful provider responses; small bounded in-memory set.
        if len(_OSM_SEARCH_CACHE) >= 128:
            _OSM_SEARCH_CACHE.pop(next(iter(_OSM_SEARCH_CACHE)))
        _OSM_SEARCH_CACHE[cache_key] = (_pyx_clock.monotonic() + (21600 if result else 3600), result)
        return list(result)


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


def _strict_osm_search_address(address, official_desa, official_kecamatan,
                               official_kabupaten, official_provinsi):
    """Require explicit region evidence in OSM search result; no extra HTTP.

    Missing fields are not treated as matches. This remains strict fallback
    validation, never a substitute for a verified official NPSN coordinate.
    """
    kab = (address.get("county") or address.get("city") or
           address.get("municipality") or address.get("state_district") or "")
    prov = address.get("state") or address.get("region") or ""
    desa = (address.get("village") or address.get("suburb") or
            address.get("hamlet") or address.get("neighbourhood") or "")
    kec = (address.get("city_district") or address.get("subdistrict") or
           address.get("district") or "")
    kab_ok = _region_matches(official_kabupaten, kab)
    prov_ok = _region_matches(official_provinsi, prov)
    desa_ok = _region_matches(official_desa, desa)
    kec_ok = _region_matches(official_kecamatan, kec)
    local_expected = bool(official_desa or official_kecamatan)
    local_ok = (desa_ok is True or kec_ok is True)
    verified = kab_ok is True and prov_ok is True and (not local_expected or local_ok)
    validation = {
        "status": "verified" if verified else "partial",
        "message": "Wilayah OSM cocok dengan master resmi" if verified else
                   "Bukti wilayah OSM belum lengkap/cocok untuk fallback",
        "provider": "OpenStreetMap/Nominatim (search addressdetails)",
        "reverse_desa": desa,
        "reverse_kecamatan": kec,
        "reverse_kabupaten": kab,
        "reverse_provinsi": prov,
        "desa_match": desa_ok,
        "kec_match": kec_ok,
        "kab_match": kab_ok,
        "prov_match": prov_ok,
    }
    return verified, validation


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

    # Public Nominatim is a shared service, not a bulk school-search backend.
    # Two focused queries at most per user action; stop on rate limiting.
    osm_query_specs = [item for item in query_specs if item[0] in {"nama+wilayah", "nama+alamat"}][:2]
    for query_id, query in osm_query_specs:
        try:
            results = _nominatim_search(query)
        except _OSMTemporarilyLimited as exc:
            osm_search_errors.append(f"{query_id}: {exc}")
            break
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

            min_similarity = 0.68 if school_like else 0.88
            if name_similarity < min_similarity:
                continue

            # Search already requests addressdetails=1. Verify regions using
            # that payload instead of generating additional reverse API calls
            # for every candidate (which could trigger HTTP 429).
            strict_ok, validation = _strict_osm_search_address(
                item.get("address") or {}, desa, kecamatan, kabupaten_kota, provinsi
            )
            if not strict_ok:
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

        if any("429" in e or "cooldown" in e.lower() for e in osm_search_errors):
            raise ValueError(
                "Koordinat resmi NPSN tidak tersedia (0,0). Pencarian cadangan "
                "OpenStreetMap sedang dibatasi HTTP 429. Tidak ada titik sekolah "
                "yang boleh dipastikan otomatis saat ini. Tunggu sebelum mencoba "
                "lagi, atau gunakan Google Maps API resmi bila dikonfigurasi. "
                "Tidak ada koordinat yang dibuat atau ditebak."
            )
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


if st is not None:
    # Cache mengurangi request berulang saat Streamlit rerun.
    lookup_npsn_online_cached = st.cache_data(ttl=21600, max_entries=512, show_spinner=False)(lookup_npsn_online)
    reverse_validate_location_cached = st.cache_data(ttl=21600, max_entries=512, show_spinner=False)(
        reverse_validate_location
    )
    geocode_npsn_fallback_cached = st.cache_data(ttl=21600, max_entries=128, show_spinner=False)(
        geocode_npsn_fallback
    )
else:
    lookup_npsn_online_cached = lookup_npsn_online
    reverse_validate_location_cached = reverse_validate_location
    geocode_npsn_fallback_cached = geocode_npsn_fallback


def _normalize_nominatim_evidence(primary):
    """Unknown/no-address responses are unavailable, not a region mismatch.

    Keep the legacy Nominatim parser AST unchanged and translate only the
    status of *absent* evidence. Any actual conflicting region remains blocked.
    """
    if (primary.get("status") == "partial" and
            not primary.get("reverse_kabupaten") and
            not primary.get("reverse_provinsi")):
        return {
            **primary,
            "status": "unavailable",
            "message": "Validator peta tidak mengembalikan data wilayah.",
            "error": "Nominatim tidak menyediakan kabupaten atau provinsi untuk koordinat ini",
        }
    return primary


def _reverse_validate_official_fresh_on_failure(latitude, longitude, desa, kecamatan, kabupaten, provinsi):
    """Cache successful/partial reverse lookups, never pin a service outage for 6h.

    Streamlit caches return VALUES, including transient unavailable results.
    A verified backup used to hide the original Nominatim failure from the
    caller, leaving the failed Nominatim response in the six-hour cache. Clear
    that exact entry before using the backup so subsequent checks can recover.
    """
    params = (latitude, longitude, desa, kecamatan, kabupaten, provinsi)
    primary = _normalize_nominatim_evidence(reverse_validate_location_cached(*params))
    if primary.get("status") == "unavailable":
        try:
            reverse_validate_location_cached.clear(*params)
        except (AttributeError, TypeError):
            # In tests or older Streamlit versions .clear may be unavailable.
            pass
    return primary


# ============================================================
# PHOTO / TIME HELPERS
# ============================================================


def _photo_sort_key(uploaded_file):
    stem = os.path.splitext(os.path.basename(uploaded_file.name))[0].strip()
    if stem.isdigit():
        return (0, int(stem), uploaded_file.name.lower())

    parts = re.split(r"(\d+)", stem.lower())
    natural = tuple(int(part) if part.isdigit() else part for part in parts)
    return (1, natural, uploaded_file.name.lower())


def validate_numeric_photo_names(uploaded_files):
    invalid = []
    duplicates = []
    seen = set()

    for uploaded_file in uploaded_files or []:
        stem = os.path.splitext(os.path.basename(uploaded_file.name))[0].strip()
        if not stem.isdigit():
            invalid.append(uploaded_file.name)
            continue
        number = int(stem)
        if number in seen:
            duplicates.append(number)
        seen.add(number)

    errors = []
    if invalid:
        errors.append(
            "Nama file harus angka saja, contoh 1.jpg, 2.jpg, 3.jpg. Tidak valid: "
            + ", ".join(invalid[:8])
        )
    if duplicates:
        errors.append(
            "Nomor foto duplikat: " + ", ".join(str(x) for x in sorted(set(duplicates)))
        )
    return errors


def generate_ordered_random_datetimes(selected_date, start_time, end_time, count):
    if count <= 0:
        return []

    start_dt = datetime.combine(selected_date, start_time)
    end_dt = datetime.combine(selected_date, end_time)

    if end_dt <= start_dt:
        raise ValueError("Jam selesai harus lebih besar daripada jam mulai.")

    total_seconds = int((end_dt - start_dt).total_seconds())
    if total_seconds + 1 < count:
        raise ValueError("Rentang waktu terlalu pendek untuk membuat jam unik untuk semua foto.")

    offsets = sorted(secrets.SystemRandom().sample(range(total_seconds + 1), count))
    return [start_dt + timedelta(seconds=offset) for offset in offsets]


def _encode_pil_image_bytes(pil_image, original_filename):
    _, ext = os.path.splitext(original_filename)
    ext = ext.lower()
    if ext not in [".jpg", ".jpeg", ".png"]:
        ext = ".jpg"

    rgb = np.array(pil_image.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    if ext in [".jpg", ".jpeg"]:
        ok, encoded = cv2.imencode(ext, bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
        mime = "image/jpeg"
    else:
        ok, encoded = cv2.imencode(ext, bgr)
        mime = "image/png"

    if not ok:
        raise ValueError(f"Gagal encode hasil foto: {original_filename}")

    return encoded.tobytes(), mime


# ============================================================
# COORDINATE JITTER HELPERS
# ============================================================


def _jitter_single_coordinate(base_latitude, base_longitude, max_radius_meters):
    if max_radius_meters <= 0:
        return base_latitude, base_longitude, 0.0

    random_gen = secrets.SystemRandom()
    angle = random_gen.uniform(0, 2 * math.pi)
    distance_m = random_gen.uniform(0, max_radius_meters)

    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = max(111_320.0 * math.cos(math.radians(base_latitude)), 1e-9)

    delta_lat = (distance_m * math.cos(angle)) / meters_per_deg_lat
    delta_lon = (distance_m * math.sin(angle)) / meters_per_deg_lon

    return (
        base_latitude + delta_lat,
        base_longitude + delta_lon,
        distance_m,
    )


# ============================================================
# BATCH FONT SIZE HELPERS
# ============================================================


def _calculate_locked_font_size_px(uploaded_files, load_image_fn, font_size_mode, font_size_percent, fixed_font_size_px):
    if font_size_mode == "fixed_px":
        return max(14, int(round(fixed_font_size_px))), []

    basis_values = []
    dimensions = []
    for uploaded_file in uploaded_files or []:
        uploaded_file.seek(0)
        image = load_image_fn(uploaded_file)
        width, height = image.size
        dimensions.append((uploaded_file.name, width, height))
        basis_values.append(min(width, height) if font_size_mode == "short_edge" else width)
        uploaded_file.seek(0)

    if not basis_values:
        return None, dimensions

    median_basis = float(np.median(basis_values))
    locked_px = max(14, int(round(median_basis * (font_size_percent / 100.0))))
    return locked_px, dimensions


# ============================================================
# STREAMLIT BATCH MODE
# ============================================================


def _render_npsn_template_checked(generate_timestamp_fn, photo_cv, raw_timestamp,
                                  selected_template, **render_kwargs):
    """Batch NPSN-only layout adapter. Original renderer and position are intact.

    Kamera GPS here means only the ORDER of lines changes: address, date/time,
    coordinates. The same ORIGINAL AVHershey renderer draws at its usual bottom
    left position with all existing font, outline, spacing and auto-fit options.
    This deliberately does not change Satu Foto or Batch Manual.
    """
    if selected_template not in ("classic", "camera_gps"):
        raise ValueError(f"Template geotag tidak dikenal: {selected_template}")

    if selected_template == "classic":
        return generate_timestamp_fn(
            photo_cv, raw_timestamp, template="classic", **render_kwargs
        )

    # Reordering is data presentation only. Do not call the Camera GPS renderer:
    # it would also move the overlay to the top and change the typeface.
    from pyx_geotag_templates import camera_gps_lines
    ordered_text = "\n".join(camera_gps_lines(raw_timestamp))
    image, info = generate_timestamp_fn(
        photo_cv, ordered_text, template="classic", **render_kwargs
    )
    if not isinstance(info, dict) or "left_margin" not in info or "bottom_margin" not in info:
        raise RuntimeError(
            "Renderer posisi Original tidak tersedia. Generate dihentikan agar "
            "hasil ZIP tidak memakai tampilan yang salah."
        )
    info = dict(info)
    info["template"] = "camera_gps"
    info["line_order"] = "alamat → tanggal/jam → koordinat"
    info["position_style"] = "original (tidak diubah)"
    return image, info


def _make_npsn_preview_renderer(generate_timestamp_fn):
    """Keep Batch NPSN live preview visually identical to exported JPGs."""
    def preview(photo_cv, raw_timestamp, **render_kwargs):
        selected = render_kwargs.pop("template", None) or "classic"
        return _render_npsn_template_checked(
            generate_timestamp_fn, photo_cv, raw_timestamp,
            selected_template=selected, **render_kwargs
        )
    return preview


def render_batch_mode(uploader_version, load_image_fn, generate_timestamp_fn):
    if st is None:
        raise RuntimeError("Streamlit belum terpasang. Jalankan pip install -r requirements.txt")

    preview_renderer = _make_npsn_preview_renderer(generate_timestamp_fn)

    state_key = "batch_generated_result"
    lookup_state_key = "batch_npsn_online_result"

    if state_key not in st.session_state:
        st.session_state[state_key] = None
    if lookup_state_key not in st.session_state:
        st.session_state[lookup_state_key] = None

    # V9.4 changes presentation only. All OCR, lookup and render routines remain untouched.
    controls_col, preview_col = st.columns([1.05, 1.35], gap="large")

    with controls_col:
        st.markdown("#### 🧰 Input & Pengaturan")
        # V9.5.2: separate cards keep NPSN and font sizing in plain sight.
        with st.container(border=False):
            with st.container(border=True):
                st.markdown("**📷 Foto batch**")
                st.caption(
                    "⚠️ Jam batch berasal dari rentang input, bukan EXIF asli. "
                    "Timestamp adalah overlay visual; EXIF tidak diubah."
                )

                # --------------------------------------------------------
                # 1. PHOTO UPLOAD
                # --------------------------------------------------------

                st.markdown("##### 1. Upload foto batch")
                with st.container(border=True):
                    batch_files = st.file_uploader(
                        "Pilih beberapa foto (JPG, JPEG, PNG)",
                        type=["jpg", "jpeg", "png"],
                        accept_multiple_files=True,
                        key=f"batch_photo_uploader_{uploader_version}",
                        help="Upload langsung beberapa foto. Tidak perlu ZIP. Nama file: 1.jpg, 2.jpg, 3.jpg, dst.",
                    )

                    sorted_files = sorted(batch_files or [], key=_photo_sort_key)
                    name_errors = validate_numeric_photo_names(sorted_files)

                    for error_text in name_errors:
                        st.error("❌ " + error_text)

                    if sorted_files and not name_errors:
                        st.success(f"✅ {len(sorted_files)} foto siap. Urutan proses mengikuti nomor file.")
                        with st.expander("📋 Daftar urutan foto", expanded=False):
                            st.dataframe(
                                pd.DataFrame(
                                [{"Urutan": i, "Nama File": f.name} for i, f in enumerate(sorted_files, start=1)]
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )
                    elif not sorted_files:
                        st.info("Upload foto yang sudah dinamai 1, 2, 3, 4, ...")

            with st.container(border=True):
                # V9.5.2: font controls are visible, not hidden under an expander.
                st.markdown("**🎨 Ukuran, bold & koordinat — langsung atur di sini**")
                with st.container(border=False):
                    st.caption(
                        "Font yang dipakai: **AVHershey Simplex Medium**. Bold sekarang bisa diatur tingkat ketebalannya sendiri."
                    )

                    size_mode_label = st.selectbox(
                        "Metode Ukuran Timestamp",
                        [
                            "Smart Uniform (Sisi Terpendek) — Recommended",
                            "% Lebar Foto (Legacy)",
                            "Fixed Pixel",
                        ],
                        index=0,
                        key=f"batch_size_mode_{uploader_version}",
                        help="Smart Uniform membuat portrait dan landscape dengan resolusi setara terlihat konsisten.",
                    )

                    if size_mode_label.startswith("Smart Uniform"):
                        batch_font_size_mode = "short_edge"
                    elif size_mode_label.startswith("% Lebar"):
                        batch_font_size_mode = "width"
                    else:
                        batch_font_size_mode = "fixed_px"

                    style_col1, style_col2 = st.columns([2, 1])
                    with style_col1:
                        if batch_font_size_mode == "fixed_px":
                            batch_fixed_font_size_px = st.number_input(
                                "Ukuran Timestamp (px)",
                                min_value=14,
                                max_value=400,
                                value=80,
                                step=1,
                                key=f"batch_fixed_size_px_{uploader_version}",
                            )
                            batch_font_size_percent = 5.0
                        else:
                            batch_font_size_percent = st.slider(
                                "Ukuran Timestamp (%)",
                                min_value=2.0,
                                max_value=8.0,
                                value=5.0,
                                step=0.1,
                                key=f"batch_font_size_percent_{uploader_version}",
                                help="Smart Uniform = persen dari sisi terpendek. Legacy = persen dari lebar foto.",
                            )
                            batch_fixed_font_size_px = 80

                    with style_col2:
                        batch_bold_enabled = st.toggle(
                            "Bold",
                            value=False,
                            key=f"batch_bold_enabled_{uploader_version}",
                            help="Aktifkan penebalan font. Ketebalannya bisa diatur di bawah.",
                        )

                    lock_batch_font_size = st.toggle(
                        "Kunci ukuran karakter seluruh batch (True Uniform)",
                        value=True,
                        key=f"batch_lock_size_{uploader_version}",
                        help="Recommended. Semua foto memakai ukuran karakter px yang sama. Jika baris terlalu panjang pada foto sempit, teks dibungkus ke baris berikutnya, bukan dikecilkan.",
                    )

                    if batch_bold_enabled:
                        batch_bold_strength_percent = st.slider(
                            "Ketebalan Bold",
                            min_value=1,
                            max_value=100,
                            value=25,
                            step=1,
                            key=f"batch_bold_strength_{uploader_version}",
                            help="1 = sangat tipis, 100 = paling tebal.",
                        )
                    else:
                        batch_bold_strength_percent = 25

                    jitter_enabled = st.toggle(
                        "Acak sedikit koordinat per foto",
                        value=False,
                        key=f"batch_jitter_enabled_{uploader_version}",
                        help="Menambahkan offset kecil di sekitar titik koordinat terpilih supaya koordinat antar foto tidak identik.",
                    )
                    if jitter_enabled:
                        jitter_radius_m = st.slider(
                            "Radius maksimum acak koordinat (meter)",
                            min_value=1,
                            max_value=30,
                            value=8,
                            step=1,
                            key=f"batch_jitter_radius_{uploader_version}",
                            help="Gunakan radius kecil agar koordinat tetap dekat dengan titik koordinat terpilih.",
                        )
                        st.caption(
                            "Offset koordinat akan dibuat acak dalam radius kecil dari titik koordinat terpilih. Cocok jika kamu ingin setiap foto tidak memakai koordinat yang persis sama."
                        )
                    else:
                        jitter_radius_m = 0
                        st.caption("Koordinat akan memakai titik koordinat terpilih secara persis untuk semua foto.")

                    size_preview = (
                        f"{int(batch_fixed_font_size_px)} px"
                        if batch_font_size_mode == "fixed_px"
                        else f"{batch_font_size_percent:.1f}%"
                    )
                    st.caption(
                        f"Preview setting: Font **AVHershey Simplex Medium** | Metode **{size_mode_label}** | Ukuran **{size_preview}** | "
                        f"True Uniform: **{'Aktif' if lock_batch_font_size else 'Nonaktif'}** | "
                        f"Bold: **{'Aktif' if batch_bold_enabled else 'Nonaktif'}**"
                        + (f" | Ketebalan: **{batch_bold_strength_percent}%**" if batch_bold_enabled else "")
                        + f" | Variasi koordinat: **{'Aktif' if jitter_enabled else 'Nonaktif'}**"
                    )

                # --------------------------------------------------------
                # 5. GENERATE
                # --------------------------------------------------------

            with st.container(border=True):
                st.markdown("**🏫 Identitas sekolah (NPSN)**")
                # --------------------------------------------------------
                # 2. ONLINE NPSN LOOKUP
                # --------------------------------------------------------
                st.markdown("##### 2. Cari NPSN & lokasi")
                with st.container(border=True):
                    npsn_value = st.text_input(
                        "Masukkan NPSN",
                        placeholder="Contoh: 20212345",
                        key=f"batch_npsn_{uploader_version}",
                        help="NPSN dipakai sebagai exact-match ke Referensi Data Kemendikdasmen. Nama sekolah tidak ditampilkan pada foto.",
                    )
                    current_npsn = _normalize_npsn(npsn_value)

                    fallback_enabled = st.toggle(
                        "Gunakan fallback geocoding HANYA jika koordinat resmi NPSN kosong / 0,0",
                        value=False,
                        key=f"batch_npsn_fallback_{uploader_version}",
                        help=(
                            "Logic utama tidak berubah: koordinat resmi Kemendikdasmen selalu diprioritaskan. "
                            "Fallback baru dipakai jika titik resmi memang 0,0, dan hanya lolos jika validasi ketat berhasil."
                        ),
                    )

                    # Jika penanda ini tidak tampil, Streamlit belum memakai file baru.
                    st.caption(f"🧩 Build validator: **{NPSN_VALIDATOR_BUILD}**")
                    google_maps_api_key = st.secrets.get("GOOGLE_MAPS_API_KEY", "")
                    if fallback_enabled:
                        st.caption(
                            "Fallback memakai beberapa jalur independen: Google Places (New), Google Geocoding, "
                            "OpenStreetMap/Nominatim, plus validasi nama & wilayah resmi NPSN. "
                            + (
                                "✅ GOOGLE_MAPS_API_KEY terdeteksi: Google Places/Geocoding aktif."
                                if _google_api_key_is_configured(google_maps_api_key)
                                else "⚠️ GOOGLE_MAPS_API_KEY belum terdeteksi. Fallback tetap mencoba OSM, tetapi sekolah yang belum ada di OSM bisa gagal ditemukan."
                            )
                        )

                    lookup_clicked = st.button(
                        "🔎 CEK NPSN & AMBIL LOKASI ONLINE",
                        type="secondary",
                        disabled=not bool(current_npsn),
                        use_container_width=True,
                        key=f"batch_lookup_npsn_{uploader_version}",
                    )

                    if lookup_clicked:
                        st.session_state[state_key] = None
                        try:
                            with st.spinner("Mengambil data resmi Kemendikdasmen dan memvalidasi koordinat..."):
                                official_info = lookup_npsn_online_cached(current_npsn)
                                official_info["fallback_enabled_at_lookup"] = fallback_enabled

                                if official_info.get("official_coordinate_valid"):
                                    # LOGIC UTAMA / LAMA: selalu dipakai bila titik resmi tersedia.
                                    validation = _reverse_validate_official_fresh_on_failure(
                                        official_info["latitude"],
                                        official_info["longitude"],
                                        official_info["desa"],
                                        official_info["kecamatan"],
                                        official_info["kabupaten_kota"],
                                        official_info["provinsi"],
                                    )
                                    validation = _resolve_unavailable_official_validation(
                                        validation,
                                        official_info["latitude"], official_info["longitude"],
                                        official_info["kabupaten_kota"], official_info["provinsi"],
                                        google_maps_api_key,
                                    )
                                    official_info["validation"] = validation
                                    official_info["coordinate_source_type"] = "official"
                                    official_info["source_name"] = "Referensi Data Kemendikdasmen (koordinat resmi)"

                                elif fallback_enabled:
                                    # OPSI KEDUA: hanya aktif bila titik resmi 0,0.
                                    try:
                                        fallback_result = geocode_npsn_fallback_cached(
                                            official_info["npsn"],
                                            official_info.get("nama_sekolah", ""),
                                            official_info.get("alamat", ""),
                                            official_info.get("desa", ""),
                                            official_info.get("kecamatan", ""),
                                            official_info.get("kabupaten_kota", ""),
                                            official_info.get("provinsi", ""),
                                            google_maps_api_key,
                                        )
                                    except (ValueError, requests.RequestException) as fallback_error:
                                        official_info["validation"] = {
                                            "status": "official_missing",
                                            "message": "Koordinat resmi belum tersedia; fallback gagal secara terpisah.",
                                        }
                                        official_info["coordinate_source_type"] = "official_missing"
                                        official_info["fallback_error"] = str(fallback_error)
                                    else:
                                        official_info["latitude"] = fallback_result["latitude"]
                                        official_info["longitude"] = fallback_result["longitude"]
                                        official_info["validation"] = fallback_result["validation"]
                                        official_info["coordinate_source_type"] = "fallback"
                                        official_info["source_name"] = fallback_result.get("provider_note", "Fallback geocoding tervalidasi")
                                        official_info["fallback"] = fallback_result

                                else:
                                    official_info["validation"] = {
                                        "status": "official_missing",
                                        "message": (
                                            "Koordinat resmi NPSN masih 0,0. Logic utama tetap dipertahankan dan "
                                            "fallback belum diaktifkan."
                                        ),
                                    }
                                    official_info["coordinate_source_type"] = "official_missing"

                                st.session_state[lookup_state_key] = official_info
                        except Exception as error:
                            st.session_state[lookup_state_key] = None
                            st.error(f"❌ Gagal mengambil NPSN: {error}")

                    npsn_info = st.session_state.get(lookup_state_key)
                    if npsn_info and npsn_info.get("npsn") != current_npsn:
                        st.info("NPSN berubah. Klik **CEK NPSN & AMBIL LOKASI ONLINE** untuk memuat data baru.")
                        npsn_info = None

                    if (
                        npsn_info
                        and not npsn_info.get("official_coordinate_valid")
                        and npsn_info.get("fallback_enabled_at_lookup") != fallback_enabled
                    ):
                        st.info(
                            "Pilihan fallback berubah. Klik **CEK NPSN & AMBIL LOKASI ONLINE** lagi agar sumber koordinat diperbarui."
                        )
                        npsn_info = None

                    validation_ok = False
                    manual_review_ok = False
                    if npsn_info is not None:
                        validation = npsn_info.get("validation", {})
                        validation_status = validation.get("status", "unavailable")
                        # Primary gate: official Kemendikdasmen NPSN coordinates.
                        # Reverse-geocoding is diagnostic ONLY for this trusted point.
                        # Geocoded fallback coordinates retain strict map verification.
                        validation_ok = _npsn_generation_authorized(npsn_info)
                        source_type = npsn_info.get("coordinate_source_type", "official_missing")
                        official_point_ok = source_type == "official" and validation_ok

                        st.success("✅ NPSN exact-match ditemukan pada Referensi Data Kemendikdasmen.")
                        st.markdown(f"📍 **Daerah untuk timestamp:** `{npsn_info['location']}`")
                        st.caption(
                            "Format daerah: Desa/Kelurahan (fallback Kecamatan) + Kabupaten/Kota + Provinsi. "
                            "Nama sekolah tidak dimasukkan ke timestamp."
                        )

                        if source_type == "official":
                            c1, c2 = st.columns(2)
                            with c1:
                                st.metric("Latitude / Lintang", f"{npsn_info['latitude']:.7f}")
                            with c2:
                                st.metric("Longitude / Bujur", f"{npsn_info['longitude']:.7f}")
                            st.success("🎯 Sumber koordinat: **titik resmi NPSN** (logic utama).")
                            if npsn_info.get("coordinate_recovery"):
                                st.caption(npsn_info["coordinate_recovery"])

                        elif source_type == "fallback":
                            fallback_result = npsn_info.get("fallback", {})
                            c1, c2 = st.columns(2)
                            with c1:
                                st.metric("Latitude Fallback", f"{npsn_info['latitude']:.7f}")
                            with c2:
                                st.metric("Longitude Fallback", f"{npsn_info['longitude']:.7f}")
                            st.warning(
                                "⚠️ Titik resmi Kemendikdasmen = 0,0. Program memakai **fallback geocoding tervalidasi**, "
                                "bukan koordinat resmi NPSN."
                            )
                            st.success(
                                "🔐 Validasi fallback lolos | "
                                f"Confidence: **{fallback_result.get('confidence', 'HIGH')}** | "
                                f"Metode: **{fallback_result.get('provider_note', '-')}**"
                            )
                            st.caption(
                                f"Konsensus query: {fallback_result.get('consensus_count', 0)} | "
                                f"Kecocokan nama: {fallback_result.get('name_similarity', 0.0) * 100:.1f}%"
                            )

                        else:
                            st.warning(
                                "⚠️ Koordinat resmi NPSN masih **0,0**. "
                                "Generate diblokir sampai ditemukan titik yang tervalidasi."
                            )
                            if npsn_info.get("fallback_error"):
                                st.error("Pencarian titik cadangan belum berhasil: " + npsn_info["fallback_error"])
                            elif not fallback_enabled:
                                st.caption("Fallback tidak diaktifkan. Titik resmi belum tersedia pada sumber utama.")

                        if official_point_ok and validation_status != "verified":
                            if validation_status == "mismatch":
                                st.warning(
                                    "🗺️ Reverse-geocoding menunjukkan wilayah berbeda dari data resmi. "
                                    "Ini PERINGATAN, bukan pemblokiran. Generate tetap tersedia "
                                    "menggunakan koordinat NPSN asli tanpa menggantinya. "
                                    "Jika dokumentasi membutuhkan presisi lokasi, periksa titik resmi pada peta."
                                )
                            else:
                                st.info(
                                    "🗺️ Validasi peta tambahan belum lengkap / tidak tersedia. "
                                    "Generate tetap tersedia menggunakan koordinat resmi Kemendikdasmen. "
                                    "Status peta belum dianggap terverifikasi."
                                )
                        elif validation_status == "verified":
                            st.success("🗺️ Validasi lokasi: " + validation.get("message", "Cocok."))
                            st.caption("Penyedia validator: " + validation.get("provider", "OpenStreetMap/Nominatim"))
                        elif validation_status == "partial":
                            st.warning("🗺️ Validasi lokasi: " + validation.get("message", "Sebagian."))
                            diagnostics = validation.get("fallback_diagnostics", "")
                            if diagnostics:
                                st.caption("Diagnostik validator cadangan: " + diagnostics)
                        elif validation_status == "unavailable":
                            st.warning(
                                "🗺️ Validasi peta otomatis belum tersedia untuk titik ini. "
                                "Koordinat resmi NPSN tetap ditampilkan tanpa perubahan, "
                                "tetapi BELUM dinyatakan terverifikasi oleh peta. "
                                "Gunakan Coba Validasi Lagi atau verifikasi manual setelah memeriksa titik."
                            )
                            diagnostics = validation.get("fallback_diagnostics", "")
                            if diagnostics:
                                st.caption("Diagnostik provider cadangan: " + diagnostics)
                            if not _google_api_key_is_configured(google_maps_api_key):
                                st.info(
                                    "Google Geocoding belum dikonfigurasi. Jika validator wilayah Indonesia "
                                    "juga gagal, administrator bisa menambahkan GOOGLE_MAPS_API_KEY "
                                    "(dengan Geocoding API aktif) ke Secrets untuk alternatif tambahan."
                                )
                            validator_error = str(validation.get("error", "")).strip()
                            if validator_error.startswith("HTTP "):
                                http_status = validator_error.split()[1] if len(validator_error.split()) > 1 else "-"
                                st.caption(f"Respons layanan peta: HTTP {http_status}.")
                            elif validator_error:
                                st.caption("Koneksi layanan peta gagal atau melewati batas waktu. Coba validasi ulang.")

                            # Jalur kontinuitas khusus titik resmi ketika seluruh API peta gagal.
                            # Tidak pernah dipakai untuk mismatch/partial/titik 0,0.
                            if _official_manual_review_allowed(npsn_info, validation):
                                with st.expander("🧭 Verifikasi mandiri titik resmi NPSN (opsional)", expanded=False):
                                    st.warning(
                                        "Ini BUKAN verifikasi peta otomatis. Periksa lokasi sekolah "
                                        "pada peta terlebih dahulu. Jika kamu lanjut, hasil akan "
                                        "ditandai sebagai 'Dikonfirmasi manual — belum diverifikasi peta'."
                                    )
                                    coord_lat = npsn_info["latitude"]
                                    coord_lon = npsn_info["longitude"]
                                    st.link_button(
                                        "🗺️ Periksa koordinat di Google Maps",
                                        f"https://www.google.com/maps?q={coord_lat:.7f},{coord_lon:.7f}",
                                        use_container_width=True,
                                    )
                                    review_key = (
                                        f"pyx_npsn_manual_review_{uploader_version}_"
                                        f"{npsn_info['npsn']}_{coord_lat:.7f}_{coord_lon:.7f}"
                                    )
                                    acknowledged = st.checkbox(
                                        "Saya sudah memeriksa titik pada peta dan memahami "
                                        "bahwa validator eksternal belum berhasil.",
                                        key=review_key,
                                        value=False,
                                    )
                                    confirmation = st.text_input(
                                        "Ketik NPSN untuk konfirmasi",
                                        key=review_key + "_type",
                                        placeholder=npsn_info["npsn"],
                                    )
                                    manual_review_ok = bool(
                                        acknowledged and _normalize_npsn(confirmation) == npsn_info["npsn"]
                                    )
                                    if manual_review_ok:
                                        st.info(
                                            "Konfirmasi manual diterima. Generate dapat digunakan, "
                                            "dan log output akan mencatat status belum diverifikasi peta."
                                        )
                                        validation_ok = True

                            # V9.5.2.4.17: retry tetap ada, tidak menyentuh mesin Generate.
                            # Sengaja tidak memakai cache 6 jam yang dapat menyimpan respons gagal.
                            if source_type == "official":
                                retry_key = f"batch_npsn_validator_retry_at_{uploader_version}"
                                now_mono = _pyx_clock.monotonic()
                                retry_at = float(st.session_state.get(retry_key, 0.0) or 0.0)
                                remaining = max(0, int(retry_at - now_mono + 0.999))
                                if st.button(
                                    "🔄 Coba Validasi Lokasi Lagi",
                                    type="secondary",
                                    disabled=remaining > 0,
                                    key=f"batch_npsn_validator_retry_{uploader_version}",
                                ):
                                    # Pembatasan 30 detik per sesi agar tidak membanjiri API publik.
                                    st.session_state[retry_key] = _pyx_clock.monotonic() + 30.0
                                    with st.spinner("Memeriksa ulang koordinat resmi pada layanan peta..."):
                                        new_validation = _normalize_nominatim_evidence(reverse_validate_location(
                                            npsn_info["latitude"],
                                            npsn_info["longitude"],
                                            npsn_info["desa"],
                                            npsn_info["kecamatan"],
                                            npsn_info["kabupaten_kota"],
                                            npsn_info["provinsi"],
                                        ))
                                        new_validation = _resolve_unavailable_official_validation(
                                            new_validation,
                                            npsn_info["latitude"], npsn_info["longitude"],
                                            npsn_info["kabupaten_kota"], npsn_info["provinsi"],
                                            google_maps_api_key,
                                        )
                                        updated_info = dict(npsn_info)
                                        updated_info["validation"] = new_validation
                                        st.session_state[lookup_state_key] = updated_info
                                        # Bersihkan cache untuk kombinasi koordinat ini saja,
                                        # supaya hasil gagal lama tidak muncul kembali saat lookup berikutnya.
                                        try:
                                            reverse_validate_location_cached.clear(
                                                npsn_info["latitude"],
                                                npsn_info["longitude"],
                                                npsn_info["desa"],
                                                npsn_info["kecamatan"],
                                                npsn_info["kabupaten_kota"],
                                                npsn_info["provinsi"],
                                            )
                                        except (AttributeError, TypeError):
                                            pass  # Kompatibilitas saat cache/Streamlit berbeda.
                                    st.rerun()
                                elif remaining > 0:
                                    st.caption(f"Coba lagi sekitar {remaining} detik. Tidak perlu mengulang NPSN.")
                        elif validation_status == "mismatch":
                            st.error("🛑 " + validation.get("message", "Lokasi tidak cocok."))
                        elif validation_status == "official_missing":
                            st.warning("🛑 " + validation.get("message", "Koordinat resmi kosong."))

                        st.caption(f"Sumber identitas & wilayah: {npsn_info['source_url']}")
                        if validation_status in {"verified", "partial", "mismatch"}:
                            st.caption(
                                "Hasil reverse-validator (informasi pembanding, bukan pengganti titik resmi) → "
                                f"Desa: {validation.get('reverse_desa', '-') or '-'} | "
                                f"Kecamatan: {validation.get('reverse_kecamatan', '-') or '-'} | "
                                f"Kab/Kota: {validation.get('reverse_kabupaten', '-') or '-'} | "
                                f"Provinsi: {validation.get('reverse_provinsi', '-') or '-'}"
                            )

            with st.container(border=True):
                st.markdown("**🕒 Jadwal & zona waktu**")
                # --------------------------------------------------------
                # 3. DATE / TIME RANGE
                # --------------------------------------------------------
                st.markdown("##### 3. Tanggal & rentang jam")
                with st.container(border=True):
                    c_date, c_start, c_end = st.columns(3)
                    with c_date:
                        batch_date = st.date_input(
                            "Tanggal",
                            value=date.today(),
                            key=f"batch_date_{uploader_version}",
                            format="DD/MM/YYYY",
                        )
                    with c_start:
                        batch_start = st.time_input(
                            "Jam Mulai",
                            value=time(13, 0, 0),
                            key=f"batch_start_{uploader_version}",
                            step=60,
                        )
                    with c_end:
                        batch_end = st.time_input(
                            "Jam Selesai",
                            value=time(16, 0, 0),
                            key=f"batch_end_{uploader_version}",
                            step=60,
                        )

                    auto_timezone = (
                        _infer_indonesia_timezone_from_province(npsn_info.get("provinsi", ""))
                        if npsn_info is not None
                        else None
                    )

                    if auto_timezone:
                        auto_title = (
                            f"Auto dari NPSN — {auto_timezone['indonesia_label']} "
                            f"({auto_timezone['gmt_label']})"
                        )
                        timezone_source = st.radio(
                            "Sumber Zona Waktu",
                            [auto_title, "Pilih Manual"],
                            horizontal=True,
                            key=f"batch_timezone_source_{uploader_version}",
                            help="Auto ditentukan dari provinsi NPSN. Manual override tetap tersedia.",
                        )
                    else:
                        timezone_source = "Pilih Manual"
                        if npsn_info is not None:
                            st.warning(
                                "⚠️ Provinsi NPSN belum dapat dipetakan otomatis ke WIB/WITA/WIT. "
                                "Silakan pilih zona waktu manual."
                            )
                        else:
                            st.info("ℹ️ Setelah NPSN berhasil dicek, zona waktu akan ditentukan otomatis dari provinsinya.")

                    if timezone_source != "Pilih Manual" and auto_timezone:
                        label_format = st.radio(
                            "Format Label Zona Waktu",
                            [
                                f"Indonesia — {auto_timezone['indonesia_label']}",
                                f"GMT — {auto_timezone['gmt_label']}",
                                f"UTC — {auto_timezone['utc_label']}",
                            ],
                            horizontal=True,
                            key=f"batch_timezone_label_format_{uploader_version}",
                            help="Offset waktunya sama; pilihan ini hanya menentukan label yang ditulis pada foto.",
                        )
                        if label_format.startswith("Indonesia"):
                            timezone_text = auto_timezone["indonesia_label"]
                        elif label_format.startswith("GMT"):
                            timezone_text = auto_timezone["gmt_label"]
                        else:
                            timezone_text = auto_timezone["utc_label"]

                        st.success(
                            f"🕒 Zona waktu otomatis dari provinsi **{npsn_info.get('provinsi', '-')}**: "
                            f"**{timezone_text}**"
                        )
                    else:
                        timezone_options = _timezone_options()
                        manual_default = (
                            auto_timezone["indonesia_label"]
                            if auto_timezone and auto_timezone["indonesia_label"] in timezone_options
                            else "WIB"
                        )
                        timezone_text = st.selectbox(
                            "Zona Waktu Manual / Override",
                            timezone_options,
                            index=timezone_options.index(manual_default),
                            key=f"batch_tz_{uploader_version}",
                            help="Pakai ini hanya jika ingin mengganti hasil zona waktu otomatis dari NPSN.",
                        )

                    st.caption(
                        "Normalnya kamu cukup mengatur **tanggal + jam mulai + jam selesai**. Zona waktu mengikuti provinsi NPSN, "
                        "dengan pilihan tampilan WIB/WITA/WIT, GMT, atau UTC. Manual override tetap tersedia."
                    )
                    st.caption(
                        "Jam diacak di dalam rentang lalu diurutkan naik sesuai file 1 → 2 → 3 → seterusnya."
                    )

        # V9.5 UI-only fingerprint of all inputs affecting batch output.
        v95_npsn_params = {
            # Invalidate ZIPs generated with the previous top-left camera renderer.
            'layout_revision': 'batch-npsn-only-order-v9.5.2.4.21',
            'template': st.session_state.get('pyx_geotag_template', 'classic'),
            'npsn_info': npsn_info,
            'manual_review_confirmed': manual_review_ok,
            'batch_date': batch_date, 'batch_start': batch_start, 'batch_end': batch_end,
            'timezone_text': timezone_text,
            'font_size_percent': batch_font_size_percent,
            'font_size_mode': batch_font_size_mode,
            'fixed_font_size_px': batch_fixed_font_size_px,
            'lock_batch_font_size': lock_batch_font_size,
            'bold_enabled': batch_bold_enabled,
            'bold_strength_percent': batch_bold_strength_percent,
            'jitter_enabled': jitter_enabled, 'jitter_radius_m': jitter_radius_m,
        }
        v95_npsn_signature = input_signature(sorted_files, v95_npsn_params)
        v95_npsn_last_key = f'v95_generated_npsn_{uploader_version}'
        v95_npsn_stale = output_is_stale(
            st.session_state.get(v95_npsn_last_key), v95_npsn_signature)

        # Generate is outside the scrolling control pane.
        st.markdown("##### 4. Generate batch")
        batch_ready = (
            bool(sorted_files)
            and not name_errors
            and npsn_info is not None
            and validation_ok
        )

        with st.container(border=True):
            if not batch_ready:
                if npsn_info is not None and not validation_ok:
                    st.error(
                        "Generate dinonaktifkan: sumber/koordinat resmi NPSN tidak valid, "
                        "atau titik fallback belum lolos validasi ketat."
                    )
                else:
                    st.info(
                        "Lengkapi foto bernomor dan cek NPSN online sampai data lokasi valid "
                        "untuk mengaktifkan generate."
                    )

            clicked = st.button(
                "🚀 GENERATE SEMUA FOTO",
                type="primary",
                disabled=not batch_ready,
                use_container_width=True,
            )

            if clicked:
                try:
                    random_datetimes = generate_ordered_random_datetimes(
                        batch_date, batch_start, batch_end, len(sorted_files)
                    )

                    locked_font_size_px = None
                    if lock_batch_font_size:
                        locked_font_size_px, _ = _calculate_locked_font_size_px(
                            sorted_files,
                            read_image_dimensions,
                            batch_font_size_mode,
                            batch_font_size_percent,
                            batch_fixed_font_size_px,
                        )

                    zip_buffer = new_archive()
                    log_rows = []
                    validation = npsn_info.get("validation", {})

                    with image_job_slot(), st.spinner(f"🖌️ Memproses {len(sorted_files)} foto..."):
                        with zipfile.ZipFile(
                            zip_buffer,
                            mode="w",
                            compression=zipfile.ZIP_STORED,
                        ) as zip_file:
                            for uploaded_file, generated_dt in zip(sorted_files, random_datetimes):
                                uploaded_file.seek(0)
                                photo_pil = load_image_fn(uploaded_file)
                                photo_cv = np.array(photo_pil)

                                actual_latitude, actual_longitude, actual_offset_m = _jitter_single_coordinate(
                                    npsn_info["latitude"],
                                    npsn_info["longitude"],
                                    jitter_radius_m if jitter_enabled else 0,
                                )
                                date_text = (
                                    f"{generated_dt.day}/{generated_dt.month}/{generated_dt.year} "
                                    f"{generated_dt.strftime('%H:%M:%S')} {timezone_text}"
                                )

                                # Dibentuk langsung dari koordinat hasil per foto supaya tidak
                                # bergantung pada variabel sementara `coordinate_text`.
                                raw_timestamp = "\n".join(
                                    [
                                        f"{actual_latitude:.7f}, {actual_longitude:.7f}",
                                        npsn_info["location"],
                                        date_text,
                                    ]
                                )

                                result_pil, _ = _render_npsn_template_checked(
                                    generate_timestamp_fn,
                                    photo_cv,
                                    raw_timestamp,
                                    selected_template=v95_npsn_params['template'],
                                    font_size_percent=batch_font_size_percent,
                                    font_size_mode=batch_font_size_mode,
                                    fixed_font_size_px=batch_fixed_font_size_px,
                                    font_size_px_override=locked_font_size_px if lock_batch_font_size else None,
                                    preserve_locked_font_size=lock_batch_font_size,
                                    bold_enabled=batch_bold_enabled,
                                    bold_strength_percent=batch_bold_strength_percent,
                                )
                                encoded_bytes, _ = _encode_pil_image_bytes(result_pil, uploaded_file.name)
                                zip_file.writestr(uploaded_file.name, encoded_bytes)

                                log_rows.append(
                                    {
                                        "Nama File": uploaded_file.name,
                                        "NPSN": npsn_info["npsn"],
                                        "Latitude": f"{actual_latitude:.7f}",
                                        "Longitude": f"{actual_longitude:.7f}",
                                        "Offset Koordinat (meter)": round(actual_offset_m, 2),
                                        "Daerah": npsn_info["location"],
                                        "Template Geotag": (
                                            "Kamera GPS" if v95_npsn_params['template'] == "camera_gps"
                                            else "Original"
                                        ),
                                        "Tanggal": generated_dt.strftime("%d/%m/%Y"),
                                        "Jam": generated_dt.strftime("%H:%M:%S"),
                                        "Zona Waktu": timezone_text,
                                        "Bold": "Ya" if batch_bold_enabled else "Tidak",
                                        "Ketebalan Bold (%)": batch_bold_strength_percent if batch_bold_enabled else 0,
                                        "Ukuran Timestamp (%)": batch_font_size_percent,
                                        "Sumber Koordinat/Daerah": npsn_info["source_name"],
                                        "URL Sumber": npsn_info["source_url"],
                                        "Status Validasi Lokasi": (
                                            "official_npsn_map_" + validation.get("status", "unavailable")
                                            if _official_npsn_coordinate_ready(npsn_info)
                                            else (
                                                "official_manual_review_unverified"
                                                if manual_review_ok else validation.get("status", "unavailable")
                                            )
                                        ),
                                        "Keterangan Validasi": (
                                            "Koordinat resmi Kemendikdasmen diprioritaskan; "
                                            "hasil reverse-geocoding hanya informasi pembanding."
                                            if _official_npsn_coordinate_ready(npsn_info)
                                            else (
                                                "Dikonfirmasi pengguna; belum diverifikasi peta eksternal"
                                                if manual_review_ok else validation.get("message", "")
                                            )
                                        ),
                                        "Sumber Waktu": "Generated/random dari rentang input; bukan EXIF asli",
                                    }
                                )
                                # Drop large RGB buffers before decoding the next
                                # uploaded photo to bound peak memory per job.
                                del photo_pil, photo_cv, result_pil, encoded_bytes

                    close_result(st.session_state.get(state_key))
                    st.session_state[state_key] = {
                        "zip_file": zip_buffer,
                        "zip_name": f"hasil_timestamp_npsn_{npsn_info['npsn']}.zip",
                        "log_rows": log_rows,
                        "template": v95_npsn_params['template'],
                    }
                    st.session_state[v95_npsn_last_key] = v95_npsn_signature
                    try:
                        from pyx_monitor_activity import record_event
                        record_event("generate_batch_npsn")
                    except Exception:
                        pass
                    st.success(f"✅ Selesai memproses {len(sorted_files)} foto.")
                except Exception as error:
                    # A partial ZIP must never linger after a failed job.
                    if 'zip_buffer' in locals() and zip_buffer is not None and not zip_buffer.closed:
                        zip_buffer.close()
                    st.error(f"❌ Gagal generate batch: {error}")

        # --------------------------------------------------------
        # RESULT
        # --------------------------------------------------------

    # Preview uses the very same rendering callback; the live time is the
    # configured start and coordinates are unjittered (final values are random).
    v95_npsn_live_text = None
    v95_npsn_live_options = None
    if sorted_files and not name_errors and npsn_info is not None and validation_ok:
        v95_npsn_live_text = "\n".join([
            f"{npsn_info['latitude']:.7f}, {npsn_info['longitude']:.7f}",
            npsn_info['location'],
            f"{batch_date.day}/{batch_date.month}/{batch_date.year} "
            f"{batch_start.strftime('%H:%M:%S')} {timezone_text}",
        ])
        v95_npsn_locked_size = None
        if lock_batch_font_size:
            v95_npsn_locked_size = preview_locked_size(
                sorted_files, load_image_fn, _calculate_locked_font_size_px,
                batch_font_size_mode, batch_font_size_percent,
                batch_fixed_font_size_px, f'npsn_{uploader_version}')
        v95_npsn_live_options = {
            'template': st.session_state.get('pyx_geotag_template', 'classic'),
            'font_size_percent': batch_font_size_percent,
            'font_size_mode': batch_font_size_mode,
            'fixed_font_size_px': batch_fixed_font_size_px,
            'font_size_px_override': v95_npsn_locked_size if lock_batch_font_size else None,
            'preserve_locked_font_size': lock_batch_font_size,
            'bold_enabled': batch_bold_enabled,
            'bold_strength_percent': batch_bold_strength_percent,
        }
    with preview_col:
        st.markdown("#### 🖼️ Preview & Hasil")
        with st.container(border=True):
            result = st.session_state.get(state_key)
            if v95_npsn_stale:
                st.warning('⚠️ NPSN, pengaturan, atau foto berubah sejak Generate terakhir. ZIP perlu Generate ulang.')
            if result is not None:
                if not v95_npsn_stale:
                    st.success("✅ Batch selesai, hasil siap diunduh.")
                    _export_style = result.get('template', 'classic')
                    st.caption(
                        "Template pada ZIP hasil: " +
                        ("Kamera GPS — urutan alamat → waktu → koordinat, posisi Original" if
                         _export_style == 'camera_gps' else
                         "Original — Koordinat → Alamat → Waktu")
                    )
                with download_data(result) as zip_download:
                    st.download_button(
                        "⬇️ Download hasil batch (ZIP)",
                        data=zip_download,
                        file_name=result["zip_name"],
                        mime="application/zip",
                        type="primary",
                        use_container_width=True,
                        disabled=v95_npsn_stale,
                    )
                if st.button("🔄 Reset Batch", use_container_width=True, key=f"reset_ui_{uploader_version}_batch_npsn"):
                    close_result(st.session_state.get(state_key))
                    st.session_state[state_key] = None
                    st.session_state[lookup_state_key] = None
                    st.session_state.pop(v95_npsn_last_key, None)
                    st.session_state.uploader_version += 1
                    st.rerun()
                batch_gallery(sorted_files, result, load_image_fn, "batch_npsn_v21", uploader_version,
                    generate_fn=preview_renderer,
                    live_timestamp=v95_npsn_live_text, live_options=v95_npsn_live_options,
                    stale=v95_npsn_stale,
                    live_caption='Contoh memakai jam mulai & koordinat dasar. Nilai acak final hanya ditentukan saat Generate.',
                )
                with st.expander("📋 Detail hasil per foto", expanded=False):
                    result_df = pd.DataFrame(result["log_rows"])
                    st.dataframe(result_df, use_container_width=True, hide_index=True)
            elif sorted_files:
                batch_gallery(sorted_files, None, load_image_fn, "batch_npsn_v21", uploader_version,
                    generate_fn=preview_renderer,
                    live_timestamp=v95_npsn_live_text, live_options=v95_npsn_live_options,
                    stale=v95_npsn_stale,
                    live_caption='Contoh memakai jam mulai & koordinat dasar. Nilai acak final hanya ditentukan saat Generate.',
                )
                st.caption(f"{len(sorted_files)} foto dipilih. Hasil timestamp muncul setelah Generate.")
            else:
                st.info("Upload foto dari panel kiri untuk melihat preview di sini.")
