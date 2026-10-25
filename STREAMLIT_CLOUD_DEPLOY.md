# Deploy AutoTimestamp V9.5.2.4.2 — Streamlit Cloud Ringan

1. Backup repository GitHub yang dipakai aplikasi `timestamp-pyx.streamlit.app`.
2. Ganti file dengan isi folder `timestamp-2-main` (bukan folder induknya).
3. **Hapus `packages.txt` lama** dari repository GitHub jika masih ada. ZIP ini memang tidak memiliki file tersebut.
4. Pastikan `requirements.txt`, `app.py`, dan `.streamlit/config.toml` ada di lokasi yang benar; entrypoint Streamlit adalah `app.py`.
5. Simpan API key Gemini hanya di Streamlit App settings → Secrets, bukan di GitHub.
6. Deploy dan uji: Upload gambar, OCR, Satu Foto, Batch Manual, Batch NPSN, Live Preview, PDF multi-halaman → JPG, gambar → JPG, download ZIP.
7. Jika masih muncul **Error installing requirements**, masalah tidak bisa didiagnosis dari screenshot saja: buka Manage app → Logs dan periksa baris error instalasi. Periksa pula versi Python yang digunakan Cloud.

**Format Converter**: Berbagai ekstensi foto, PDF, SVG (bergantung library Cairo), HEIC/AVIF (bergantung decoder) → JPG. Word, Excel, PowerPoint, ZIP, EXE, atau video tidak didukung.

**Tidak ada perubahan** pada proses OCR, engine renderer timestamp, pengaturan waktu, Batch Manual/NPSN, dan kompresi JPG.
