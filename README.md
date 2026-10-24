# AutoTimestamp — V9.3 (OCR Auto-Fill + Batch Manual Multi-Baris)

Aplikasi Streamlit untuk membuat overlay timestamp gaya GPS Camera.

## Mode

- **Satu Foto:** upload foto, input timestamp, atau paste/upload screenshot untuk OCR Gemini.
- **Batch Manual:** foto bernomor `1.jpg`, `2.jpg`, dst. dan koordinat/lokasi manual atau OCR. Jam batch dihasilkan secara acak lalu berurutan sesuai nomor foto.
- **Batch NPSN Online:** cari NPSN di Referensi Data Kemendikdasmen, ambil lokasi dan validasi koordinat. Jika koordinat resmi kosong, fallback peta opsional tersedia dengan pemeriksaan tambahan.

## Baru: hasil OCR langsung mengisi koordinat

1. Pilih **Satu Foto** atau **Batch Manual**, buka tab **OCR Screenshot (Gemini AI)**.
2. Paste screenshot dengan Ctrl+V atau upload gambar. OCR berjalan otomatis jika API key terpasang.
3. Kolom **Koordinat — otomatis dari OCR** langsung terisi dari baris pertama. Digit dan spasi pada hasil pembacaan tidak dibulatkan.
4. Kotak **Isi Teks Timestamp / Timestamp Acuan** juga terisi tiga baris. Mengedit kolom koordinat mengubah baris pertamanya; mengedit teks lengkap akan memperbarui kolom koordinat.
5. Untuk membandingkan dengan keluaran Gemini, buka **Hasil OCR mentah**. Periksa koordinat pada screenshot asli sebelum Generate; OCR tidak selalu tepat.

Contoh:

```text
-6.5500687, 107.4378152
Cipaisan, Purwakarta, Jawa Barat
7/10/2026 13:12:08 WIB
```

Perubahan ini **tidak mengubah gaya, font, bold, posisi maupun renderer timestamp**. Pemformatan akhir masih mengikuti fungsi `parse_timestamp` yang sudah ada.

## Batch Manual mendukung alamat 4+ baris (V9.3)

Baris pertama diperlakukan sebagai koordinat, baris berikutnya sebagai alamat,
dan tanggal/jam dikenali **berdasarkan pola tanggal**, bukan posisi baris ketiga.
Saat proses batch, tanggal dan jam di foto tetap mengikuti pengaturan batch;
jam yang tertulis di acuan dipakai untuk mengenali zona waktu bila tersedia.

Contoh 4 baris:

```text
3.2060390, 99.2981530
Desa Panombean Baru, Bandar Masilam,
Simalungun, Sumatera Utara
24/10/2026 14:36:41 WIB
```

Saat foto terlalu pendek untuk memuat semua baris, ukuran font akan otomatis
mengecil seperlunya (termasuk bila kunci ukuran batch diaktifkan). Preview
urutan baris tersedia sebelum generate.

## Tampilan (V9.3 UI)

- Layout lebar: input di kolom kiri, tombol buat dan hasil di kolom kanan (menempel saat scroll di desktop, menumpuk di HP).
- Tema ada di `.streamlit/config.toml`; gaya tambahan ada di blok CSS `app.py`.
- Hanya tampilan yang berubah. Renderer, OCR, parser, dan mode batch tidak diubah.

## Deploy ke Streamlit Community Cloud

1. Push semua file ke GitHub (`.streamlit/secrets.toml` jangan ikut; sudah ada di `.gitignore`).
2. Di share.streamlit.io pilih repo, branch, dan `app.py` sebagai file utama.
3. Di Advanced settings > Secrets, isi `GEMINI_API_KEY` (lihat `.streamlit/secrets.toml.example`).

## Instalasi

```bash
pip install -r requirements.txt
streamlit run app.py
```

Aplikasi perlu internet untuk Gemini OCR, lookup NPSN, serta `git clone` font Hershey saat pertama dijalankan (kecuali font sudah tersedia lokal).

Untuk Gemini OCR, buat `.streamlit/secrets.toml` (contoh: `secrets.toml.example`):

```toml
GEMINI_API_KEY = "MASUKKAN_API_KEY_ANDA"
# Opsional untuk fallback NPSN tertentu
GOOGLE_MAPS_API_KEY = "MASUKKAN_API_KEY_ANDA"
```

Jangan commit file secret asli. `.gitignore` telah diperbaiki. Screenshot yang di-OCR dikirim ke layanan Gemini; periksa kebijakan data yang berlaku.

## Penting

- OCR dan geocoding bisa menghasilkan angka/alamat keliru. Verifikasi manual.
- Jam Batch Manual dan Batch NPSN merupakan jam buatan berdasarkan rentang, bukan waktu pengambilan/EXIF asli. Overlay bukan bukti autentik waktu/lokasi pengambilan.
- Simpan foto asli terpisah dari foto hasil overlay.

## Tes helper OCR tanpa layanan eksternal

```bash
python -m unittest discover -s tests -v
```
