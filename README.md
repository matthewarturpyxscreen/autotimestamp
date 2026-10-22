# Timestamp Generator Pink V9.3 — Smart Replication

## Menjalankan
`pip install -r requirements.txt` lalu `streamlit run app.py`.

Deploy Streamlit Cloud: main file `app.py`; copy konfigurasi secret yang diperlukan dari `secrets.toml.example` ke panel Secrets (jangan commit kunci API).

## Revisi
- Native Streamlit theme pink dengan CSS kompak dan layout wide. Semua mode dan alur tetap ada.
- Default font 6,5%; pengaturan tersedia hingga 12% atau mode fixed pixel.
- Bold sintetis dibatasi maksimum 2px dan tepi hitam tidak digandakan. Mode nonbold tidak diubah.
- Font AVHershey Simplex Medium, warna, margin, jarak baris dan seluruh parameter dasar rendering tetap.

## Catatan penting
- Panjang teks memicu auto-fit sehingga ukuran hasil bisa lebih kecil dari ukuran awal. Pakai mode kunci ukuran pada batch bila dibutuhkan konsistensi ukuran.
- Waktu yang dimasukkan manual atau dibuat acak adalah overlay, bukan bukti waktu/lokasi foto asli. Untuk kepentingan audit, pertahankan sumber foto original.
- UI dipadatkan tetapi scroll masih mungkin pada layar kecil dan panel OCR/batch panjang.

## Smart Replication (mode tambahan V9.3)
1. Pilih **✨ Smart Replication** pada navigasi mode.
2. Paste screenshot geotag referensi (Ctrl+V) atau upload screenshot, lalu klik **Baca screenshot dengan Gemini**. OCR membutuhkan `GEMINI_API_KEY`.
3. Upload satu atau beberapa foto pengganti. Koreksi teks hasil OCR sebelum ekspor.
4. Atur ukuran dan bold; hasil preview mengikuti perubahan kontrol. Render font lama tetap dipakai.
5. Centang konfirmasi pemeriksaan metadata dan klik **Siapkan hasil ZIP** lalu download.
6. ZIP menyertakan `overlay_manifest.json` yang menjelaskan bahwa timestamp ditambahkan secara digital, bukan metadata pengambilan asli.

**Yang dipertahankan:** mode Satu Foto, Batch Manual, Batch NPSN Online, OCR screenshot, sumber font dan engine rendering.

**Belum tersedia di V9.3:** deteksi otomatis ukuran/posisi/ketebalan dari screenshot, perbandingan pixel-perfect, penyimpanan proyek/database, dan validasi hasil OCR ke metadata EXIF. Preview menggunakan layout Streamlit yang diringkas (pada monitor tertentu masih perlu scroll).

**Perhatian:** Foto dan waktu/lokasi asli tetap perlu diverifikasi secara mandiri. File hasil tidak boleh disajikan sebagai bukti pengambilan pada waktu atau lokasi yang tidak benar.
