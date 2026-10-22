# AutoTimestamp Streamlit — V10

Aplikasi Streamlit untuk membuat overlay timestamp gaya GPS Map Camera.

## Layout

- **Sidebar** = semua pengaturan gaya (ukuran, bold, kunci ukuran batch, acak koordinat). Satu tempat untuk semua mode, nilainya tetap saat pindah mode.
- **Kolom kiri** = input bertahap (Foto → Teks/Lokasi → Tanggal & jam).
- **Kolom kanan** (menempel saat scroll di layar lebar) = checklist status, tombol Generate, hasil + tombol download, dan **preview live** pada foto pertama dengan pengaturan yang sedang aktif.

## Mode

1. **📷 Satu Foto** — upload 1 foto, ketik/tempel teks atau OCR screenshot (Gemini), generate.
2. **🗂️ Batch Manual** — foto bernama `1.jpg, 2.jpg, ...`, koordinat & lokasi diketik atau di-OCR, tanggal + rentang jam.
3. **🏫 Batch NPSN** — foto bernama `1.jpg, 2.jpg, ...`, masukkan NPSN (Enter = cek). Koordinat & daerah diambil dari
   Referensi Data Kemendikdasmen (exact-match), divalidasi lewat reverse-geocoding OpenStreetMap/Nominatim.
   Nama sekolah tidak masuk overlay. Generate hanya aktif bila validasi `verified`
   (atau validator `unavailable` dan kamu mencentang "lanjutkan tanpa validator"; `mismatch` selalu diblokir).

Output batch: ZIP berisi foto hasil + `timestamp_log.csv` (juga bisa diunduh terpisah).

> Jam pada mode batch dibuat acak dari rentang input (tetap berurutan sesuai nomor foto), **bukan** waktu asli.
> Log CSV menandai ini. Foto hasil di-encode ulang sehingga tidak membawa metadata EXIF asli.

## Struktur kode

| File | Isi |
|---|---|
| `app.py` | entry point + mode Satu Foto |
| `batch_page.py` | halaman batch bersama (foto, jam, preview, generate, hasil) |
| `batch_manual.py`, `batch_npsn.py` | panel sumber lokasi masing-masing mode |
| `ui.py` | CSS, sidebar gaya, panel OCR, panel tanggal/zona waktu, preview |
| `common.py` | logika tanpa UI: nama foto, jam acak, zona waktu, pemroses batch paralel + ZIP |
| `engine.py` | mesin render overlay (tanpa Streamlit/OpenCV) |
| `ocr.py` | OCR Gemini |
| `npsn_lookup.py` | scrape NPSN, validasi Nominatim, fallback geocoding |

## Instalasi & jalankan

```bash
pip install -r requirements.txt
streamlit run app.py
```

Font AVHershey Simplex Medium diunduh otomatis sekali (1 file TTF) ke `Hershey_font_TTF/`.

## Secrets

`.streamlit/secrets.toml` atau Streamlit Cloud Secrets (lihat `secrets_toml.example`):

```toml
GEMINI_API_KEY = "YOUR_API_KEY"          # untuk OCR
GOOGLE_MAPS_API_KEY = "YOUR_API_KEY"     # opsional, hanya fallback NPSN dengan koordinat resmi 0,0
```

Environment variable dengan nama yang sama juga dibaca bila secrets tidak ada.
