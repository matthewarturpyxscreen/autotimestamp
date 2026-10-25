# AutoTimestamp V9.5 — Smart Preview Workspace

**Upgrade terbatas dari V9.4.1 (UI-only).** Lima fitur: live preview,
thumbnail foto bisa diklik, zoom/fit, before/after, dan peringatan hasil
Generate kedaluwarsa setelah input berubah. Ketiga mode tetap tersedia.

### Cara pakai fitur V9.5

1. Pilih **Satu Foto**, **Batch Manual**, atau **Batch NPSN Online**.
2. Upload foto dan isi OCR/koordinat/alamat/jadwal seperti biasa.
3. Di panel kanan, buka **Live Preview** untuk melihat perubahan input tanpa
   menjalankan Generate. Renderer preview memanggil fungsi renderer asli.
4. Untuk batch, klik **gambar thumbnail** (5 per halaman) untuk pindah foto.
   Gunakan panah untuk foto di luar halaman yang terlihat.
5. Gunakan slider **Zoom 50–200%** atau **Fit** untuk kembali ke 100%.
6. Pilih **Before / After** untuk melihat foto asli dan overlay berdampingan.
7. Klik **Generate** untuk membuat file final; **Hasil Generate** menunjukkan
   konten persis dari hasil/ZIP yang tersimpan. Download tetap mempertahankan
   resolusi foto asli dan mekanisme ekspor lama.
8. Jika ada perubahan setelah Generate, muncul peringatan **hasil lama** dan
   unduhan lama dinonaktifkan sampai Generate ulang.

**Khusus batch:** Live Preview menggunakan jam mulai dan koordinat dasar.
Tanggal/jam acak berurutan serta offset koordinat (jika diaktifkan) hanya
akan diputuskan oleh proses Generate asli. Jangan menganggap live preview
sebagai keluaran final yang dipilih acak.

**Batas pengujian:** fungsi inti, sinkronisasi input, rendering via callback,
fungsi zoom, navigasi thumbnail, dan paket diperiksa otomatis. Pemeriksaan
interaktif browser Streamlit perlu dicoba di instalasi Anda.
Lihat `CHANGELOG_V9.5.txt` dan `CORE_V941_AST_SHA256.json`.

---

# AutoTimestamp — V9.4 (Workspace Dashboard)

## Fokus perubahan V9.4: antarmuka saja

Ketiga mode tetap tersedia: **Satu Foto**, **Batch Manual**, dan **Batch NPSN Online**.
Layout desktop sekarang menggunakan **dua panel berdampingan**:

- **Kiri — Input & Pengaturan:** upload foto, OCR atau NPSN, input waktu, dan tombol Generate.
  Bagian input memiliki scroll sendiri sehingga pengguna tidak perlu scroll seluruh halaman.
- **Kanan — Preview & Hasil:** foto asli langsung tampak setelah upload; setelah Generate,
  foto hasil muncul di tempat yang sama dan tombol **Download** diletakkan sebelum preview.
- **Pengaturan lanjutan:** metode ukuran, bold, ukuran font, dan variasi koordinat bisa dibuka
  melalui panel lipat sehingga tidak memenuhi tampilan awal.
- **Tema:** soft pink/putih dengan area kerja lebar (`layout="wide"`).

**Tidak diubah di V9.4:** fungsi OCR dan sinkronisasi kolom, parser Batch Manual 4+ baris,
lookup & validasi NPSN, cara generate tanggal/jam batch, font/renderer, dan format unduhan.

**Catatan preview:** foto asli tampil sebelum Generate; timestamp pada preview hasil baru
muncul setelah tombol Generate ditekan. Ini bukan live rendering saat mengetik.

**Tampilan:** dirancang untuk layar desktop. Pada layar kecil, kolom dapat ditumpuk
secara responsif oleh Streamlit. Aplikasi tidak diuji di browser selama pembuatan paket
karena Streamlit tidak tersedia pada lingkungan pengujian.

---

## Fitur dari V9.3

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

## V9.4.1 — Compact Workspace (UI only)

- **Satu Foto:** tab Foto / OCR & Teks / Pengaturan.
- **Batch Manual:** tab Foto / OCR & Teks / Jadwal / Pengaturan.
- **Batch NPSN:** tab Foto / NPSN / Jadwal / Pengaturan.
- Scroll internal tetap sepanjang 610 px pada V9.4 dihapus. Pada monitor kecil, halaman/isi tab tertentu masih mungkin memerlukan scroll biasa.
- Preview gambar utama dibatasi sampai 560 × 320 piksel untuk **tampilan saja**. Resolusi file hasil tidak berubah.
- Pada Batch Manual dan Batch NPSN, gunakan galeri 4 thumbnail dan tombol nama file untuk mengganti foto. Sebelum Generate menampilkan foto asli, setelah Generate menampilkan hasil dari ZIP untuk foto yang dipilih.
- Lihat `CHANGELOG_V9.4.1.txt` untuk rincian dan cakupan yang dipertahankan.

## V9.5.1 — Konverter JPG mandiri

Mode keempat **🖼️ Konverter JPG** ditambahkan di navigasi utama. Mode ini sama sekali
terpisah dari engine OCR Gemini, timestamp AVHershey, serta kedua mode Batch.

**Input yang didukung** (selama decoder/dependensinya tersedia):

- Foto/gambar: JPG/JPEG/JPE/JFIF, PNG/APNG, WebP, TIFF, GIF, BMP/DIB, ICO, PPM/PGM/PBM, TGA, PSD, PCX, JPEG2000 (JP2/J2K), AVIF, HEIC/HEIF.
- PDF: tiap halaman menjadi JPG terpisah, contoh `surat_page_001.jpg`.
- SVG: dirender secara aman dengan CairoSVG (tanpa referensi eksternal).
- Office: DOC/DOCX, PPT/PPTX, XLS/XLSX, ODT/ODS/ODP, melalui **LibreOffice** jika tersedia di server. Ini merupakan dependensi *sistem*, bukan sekadar paket pip.

**Penting:** Tidak semua jenis file dapat secara bermakna diubah menjadi JPG. Format
seperti ZIP, EXE, video, media audio, file biner khusus, dan file terenkripsi
tidak didukung. Format Office yang tidak bisa diproses oleh LibreOffice di server
akan memberikan pesan gagal pada file terkait (bukan membuat gambar palsu).

Cara pakai:

1. Jalankan aplikasi seperti biasa: `pip install -r requirements.txt` lalu `streamlit run app.py`.
2. Buka tab **🖼️ Konverter JPG** di atas, upload satu atau beberapa file.
3. Pilih preset **Seimbang (88)**, **Ukuran lebih kecil (75)**, atau **Detail tinggi (95)**.
4. Pilih sisi terpanjang output (Asli/1280/1920/2560/4096), resolusi PDF (120–300 DPI), warna latar saat sumber transparan, dan apakah semua halaman/frame dikonversi.
5. Klik **KONVERSI KE JPG**, lihat tiap foto melalui galeri, unduh JPG individual atau ZIP berisi seluruh JPG yang berhasil.

Optimasi menggunakan Pillow JPEG `optimize=True` + `progressive=True`, subsampling
adaptif, EXIF orientation correction, alpha compositing, Lanczos downsampling, dan
PDFium rasterization. Output menghapus metadata EXIF/GPS (karena metadata lama
tidak selalu akurat setelah konversi); **simpan file asli** bila metadata penting.
Konversi dari dokumen atau format multi-halaman dapat menghasilkan banyak JPG,
sehingga ukuran total keluaran tidak selalu lebih kecil daripada input.

Batas aman mode converter: maks. 80 file, 100 MB/file, total 250 JPG, 40 megapiksel
per hasil, total data JPG 400 MB. Input sumber gambar yang lebih dari 120 MP
ditolak. File yang gagal dilaporkan satu per satu tanpa membatalkan hasil lain.

Untuk mengaktifkan konversi Office pada Linux/deployment, **instal LibreOffice
secara terpisah** (contoh Ubuntu: `sudo apt-get install libreoffice`). Pada
hosting tanpa izin instalasi paket sistem, DOCX/PPTX/XLSX mungkin tidak tersedia,
sementara JPG/PNG/PDF tetap berfungsi. Karena Office bisa berisi konten aktif,
hanya unggah dokumen yang dipercaya dan pertimbangkan menjalankan converter
di lingkungan terisolasi.

Pengujian: `python -m pytest -q` (tes integrasi LibreOffice otomatis dilewati
jika LibreOffice atau `python-docx` tidak terpasang).
