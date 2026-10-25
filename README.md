# AutoTimestamp V9.5.2.3 — Clean Cloud UI

Versi dasar: **V9.5.2.2**. Revisi ini **hanya memperluas CSS antarmuka**
untuk menyembunyikan menu/header bawaan Streamlit yang dikenali.
Pengaturan `.streamlit/config.toml` tetap memakai `toolbarMode = "minimal"`.

## Di Streamlit Community Cloud (timestamp-pyx.streamlit.app)

1. Unggah pembaruan file ke repository GitHub yang digunakan Streamlit Cloud,
   termasuk folder `.streamlit/config.toml`.
2. Pastikan entrypoint aplikasi tetap `app.py`, lalu tunggu deploy otomatis selesai.
3. Buka `https://timestamp-pyx.streamlit.app/` di tab incognito dan periksa
   toolbar di kanan atas. CSS terbaru mencoba menyembunyikan elemen toolbar,
   menu, badge, dan ikon GitHub yang dikenali.
4. **Jika masih muncul:** gunakan URL resmi
   `https://timestamp-pyx.streamlit.app/?embed=true`.

**Batasan penting:** Tidak ada pengaturan resmi agar `?embed=true`
menjadi nilai default pada domain Streamlit Community Cloud.
`st.query_params` juga tidak dapat membaca/mengatur parameter tersebut.
Cloud dapat mengubah struktur UI, membuat selector CSS tidak lagi berlaku;
beberapa kontrol hosting juga bisa berada di luar cakupan CSS aplikasi.
Karena itu V9.5.2.3 **tidak menjamin** toolbar hilang pada URL biasa.

Perubahan ini hanya menyembunyikan elemen visual, **bukan** membatasi akses
GitHub, izin edit, atau visibilitas aplikasi. Jika ingin melindungi source
code, atur akses repository GitHub sebagai private sesuai kebutuhan.

## Batas scope dan pengujian

- HANYA CSS toolbar dalam `app.py` yang diedit.
- Seluruh bagian `app.py` selain CSS itu **sama persis** dengan V9.5.2.2.
- `batch_manual.py`, `batch_npsn.py`, `ocr_fields.py`, `workspace_preview.py`,
  `jpg_converter.py`, `jpg_converter_ui.py`, `requirements.txt`, dan
  `.streamlit/config.toml` **identik byte demi byte** dengan V9.5.2.2.
- Sintaks dan pengujian otomatis dijalankan; *belum* divalidasi langsung di
  browser Community Cloud sebagai pemilik/viewer.

---

# AutoTimestamp V9.5.2.2 — Toolbar Clean View (UI/hosting only)

Dibangun dari **V9.5.2.1 Live Preview Hotfix**, tanpa perubahan engine.

## Menyembunyikan toolbar Share / Star / Edit / GitHub

- File `.streamlit/config.toml` mengaktifkan `client.toolbarMode = "minimal"`.
- CSS dalam `app.py` menyembunyikan elemen toolbar/header Streamlit yang
  diketahui. Karena struktur DOM Streamlit Community Cloud dapat berubah,
  CSS saja **tidak menjamin** semua tombol Cloud hilang di setiap versi.
- **Cara resmi untuk tampilan paling bersih** saat membagikan aplikasi publik:
  gunakan `https://NAMA-APLIKASI.streamlit.app/?embed=true`. Jika URL
  sudah mengandung `?foo=bar`, tambah `&embed=true`.
- Saat menggunakan `?embed=true`, toolbar dan padding bawaan dihilangkan
  oleh Streamlit. Jika ingin tata letak normal untuk admin, buka URL tanpa
  parameter tersebut.
- Konfigurasi ini **tidak** mengubah pengaturan visibilitas publik/private,
  hak akses, atau keamanan repo GitHub. Gunakan repo private dan pengaturan
  privasi Streamlit Community Cloud sesuai kebutuhan.

## Deploy

1. Ekstrak paket, commit seluruh folder `timestamp-2-main` termasuk `.streamlit/config.toml`.
2. Deploy/redeploy lewat Streamlit Community Cloud dengan entrypoint `app.py`.
3. Uji `?embed=true` dari browser **incognito** (viewer) agar hasil tampilan
   tidak terpengaruh kontrol khusus pemilik/developer.
4. Pastikan fitur lama: Generate, OCR, Batch Manual, Batch NPSN, JPG Converter.

Perubahan yang disengaja: hanya stylesheet di `app.py`, konfigurasi toolbar,
README, dan dokumentasi/pengujian. `generate_timestamp_image`, modul OCR,
Batch Manual, Batch NPSN, converter, dan dependensi tidak diubah.

---

# AutoTimestamp V9.5.2 — Layout Terpisah, Preview Lebih Besar

Penyempurnaan antarmuka dari **V9.5.1** (bukan versi engine baru).
Tidak ada perubahan logika OCR, Generate Satu Foto, Batch Manual, Batch NPSN,
font AVHershey, timezone, encoding output, atau konverter JPG.

### Yang berubah di V9.5.2

- **Tidak ada tab berlapis** dalam panel Input & Pengaturan untuk tiga mode
  timestamp. Foto, ukuran & gaya teks, OCR/teks (atau identitas NPSN), dan
  jadwal memiliki **kartu terpisah** sehingga bisa langsung ditemukan.
- **Ukuran font, metode ukuran, bold, dan opsi koordinat** ditampilkan langsung,
  tidak disembunyikan dalam *Pengaturan Lanjutan*. Kartu ukuran ada tepat setelah
  foto agar tidak perlu mencari di bagian bawah.
- **OCR screenshot** tetap tersedia melalui panel buka/tutup tersendiri; saat
  screenshot berubah, auto-fill koordinat dan teks tetap mengikuti cara sebelumnya.
- **Preview utama lebih luas**, batas tampilan **820 × 500 piksel** dan otomatis
  menyesuaikan lebar panel (tidak mengubah resolusi/ukuran file hasil).
- **Slider Zoom dan tombol Fit dihapus**. Preview ditampilkan pada ukuran bawaan;
  pilihan Live Preview, Foto Asli, Before/After, Hasil Generate, dan galeri
  thumbnail tetap berfungsi.
- **Konverter JPG tidak berubah** dalam pembaruan ini.

> Karena tidak ada tab berlapis lagi, halaman masih bisa di-scroll secara normal
> jika jendela browser kecil atau bagian OCR dibuka. Tidak ada scroll internal
> yang memaksa pengguna menavigasi satu panel tersembunyi.

### Jalankan dan uji

```bash
pip install -r requirements.txt
streamlit run app.py
python -m pytest -q
```

Silakan uji ukuran foto tampilan, perubahan ukuran font tanpa klik tab,
OCR Auto-Fill, galeri batch, serta unduhan pada browser tempat deployment.
Pengujian otomatis dapat dijalankan tanpa koneksi Gemini. Smoke test visual
browser Streamlit tidak tersedia di lingkungan pembangunan ZIP.

---

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


## Update V9.5.2.4 — Streamlit Cloud Performance

See `CHANGELOG_V9.5.2.4_CLOUD_PERFORMANCE.md`, `STREAMLIT_CLOUD_DEPLOY.md` and `TEST_REPORT_V9.5.2.4.md` for performance optimization, Cloud package setup and tests. OCR, timestamp Generate, batch logic, output font and codec are unchanged.
