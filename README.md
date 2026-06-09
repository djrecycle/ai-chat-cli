# DJ Chat Ai

Chat AI di terminal dengan tampilan berwarna (Rich), mendukung **Ollama** dan **LocalAI**.

## Fitur

- UI terminal dengan banner, panel, dan render Markdown
- Mode full-screen yang lebih ramah: header status, sidebar history/model, toolbar aksi, copy/edit dengan klik
- Streaming respons dari model lokal
- Baca file lokal sebagai konteks chat (`/file`, `ask --file`)
- Auto suggestion di input chat untuk command dan riwayat prompt
- Ganti provider/model tanpa restart (`/provider`, `/model`)
- Riwayat chat persisten di `~/.config/ai-chat-cli/sessions`
- Riwayat input (prompt-toolkit)
- Konfigurasi persisten di `~/.config/ai-chat-cli/config.json`

## Instalasi

### Prasyarat

- Python 3.10 atau lebih baru
- `python3-venv` untuk membuat virtualenv
- Salah satu backend AI:
  - **Ollama** berjalan di `http://127.0.0.1:11434`
  - **LocalAI** berjalan di `http://127.0.0.1:8080`
  - **OpenAI/Gemini** dengan API key

Di Ubuntu/Debian:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
```

### Instalasi cepat

```bash
# Masuk ke folder project
cd ~/ai-chat-cli

# Buat venv dengan Python 3 sistem (disarankan)
./setup-venv.sh
source .venv/bin/activate

# Jalankan aplikasi
./aichat
```

Script `setup-venv.sh` akan membuat ulang `.venv`, memasang dependency utama,
dan memasang package project dalam mode editable.

### Instalasi manual

Gunakan cara ini jika ingin mengontrol langkah instalasi sendiri:

```bash
cd ~/ai-chat-cli
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

aichat --help
aichat
```

> **Penting:** Jangan buat venv dari terminal Cursor IDE — bisa ikut memakai Python AppImage Cursor dan venv jadi rusak (`source .venv/bin/activate` gagal / `./aichat` crash). Gunakan terminal biasa di laptop Anda.

### Instalasi fitur dokumen

Untuk membaca PDF, DOCX, dan gambar OCR lewat `/file`, install dependency opsional:

```bash
source .venv/bin/activate
pip install ".[documents]"
```

Jika muncul error `This environment is externally managed`, berarti `pip` sedang
dijalankan ke Python sistem. Aktifkan `.venv` dulu atau panggil pip dari venv:

```bash
.venv/bin/python -m pip install ".[documents]"
```

Untuk OCR gambar, install Tesseract di sistem:

```bash
sudo apt install tesseract-ocr tesseract-ocr-ind
```

### Menjalankan aplikasi

Jika venv sudah aktif:

```bash
aichat
```

Tanpa mengaktifkan venv:

```bash
./aichat
```

Atau langsung via modul Python:

```bash
.venv/bin/python -m chat_cli
```

### Update setelah ada perubahan kode

Jika dependency tidak berubah, cukup jalankan lagi aplikasinya. Jika dependency
berubah atau venv rusak:

```bash
./setup-venv.sh
source .venv/bin/activate
```

### Error pip `JSONDecodeError` / PyPI timeout

Jika `pip install` gagal parse JSON dari `pypi.org`, itu masalah koneksi ke PyPI (bukan bug project). Solusi:

```bash
# Opsi 1 — pakai script setup (sudah ada fallback mirror + paket apt)
./setup-venv.sh

# Opsi 2 — mirror manual
source .venv/bin/activate
pip install --no-cache-dir \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --trusted-host mirrors.aliyun.com \
  -r requirements.txt
pip install -e .

# Opsi 3 — paket Ubuntu (offline-friendly)
sudo apt install python3-venv python3-click python3-rich python3-prompt-toolkit
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install --no-deps --no-build-isolation -e .
```

## Penggunaan

```bash
# Default (Ollama) — mode chat interaktif
aichat

# Bantuan & versi
aichat --help
aichat --version

# Opsi global (Click)
aichat --model qwen2.5:1.5b --provider ollama
aichat -m qwen2.5:1.5b -p ollama -t 0.8

# Subcommand
aichat ask "Apa itu Python?"
aichat ask --file ./README.md "Ringkas dokumen ini"
aichat models
aichat status
aichat config
aichat config --save

# Atau via modul Python
python -m chat_cli
python -m chat_cli ask "Halo"
```

### Perintah dalam chat

Saat mengetik di input chat, aplikasi akan memberi suggestion abu-abu untuk
command seperti `/file`, `/provider`, `/model`, serta prompt dari riwayat.
Tekan tombol panah kanan atau `Ctrl-F` untuk menerima suggestion.

| Perintah | Keterangan |
|----------|------------|
| `/file <path> [pertanyaan]` | Baca file teks, DOCX, PDF, atau gambar OCR |
| `/file` | Buka file browser CLI, lalu ringkas file yang dipilih |
| `/file --browse [pertanyaan]` | Buka file browser CLI dengan instruksi khusus |
| `/help` | Bantuan |
| `/new` | Buat sesi chat baru |
| `/delete` | Hapus sesi chat aktif |
| `/models` | Daftar model |
| `/model <nama>` | Ganti model |
| `/provider ollama\|localai` | Ganti backend |
| `/clear` | Hapus riwayat |
| `/system <teks>` | Ubah system prompt |
| `/thinking on\|off` | Tampilkan/sembunyikan proses berpikir |
| `/status` | Cek koneksi |
| `/save` | Simpan config |
| `/exit` | Keluar |

Saat `/thinking on`, alur berpikir ditampilkan dalam blok visual terpisah
berlabel `Proses berpikir`, sedangkan respons final tampil sebagai `Jawaban utama`.

Contoh membaca file di mode chat:

```text
/file ./README.md ringkas isi dokumen ini
/file ./laporan.docx ambil poin penting
/file ./kontrak.pdf jelaskan risiko utama
/file ./nota-belanja.jpg baca teks pada gambar
/file "~/Documents/catatan rapat.txt" buatkan poin keputusan
/file
/file --browse jelaskan poin penting dan risiko utamanya
```

Di file browser CLI: ketik nomor untuk masuk folder atau memilih file, `..` untuk naik folder,
`/teks` untuk filter nama file, `/` untuk menghapus filter, dan `q` untuk batal.

File teks seperti `.txt`, `.md`, `.py`, `.json`, `.csv`, dan log bisa dibaca langsung.
Untuk DOCX, PDF, dan gambar, install paket opsional seperti di bagian
**Instalasi fitur dokumen**:

```bash
pip install ".[documents]"
```

Untuk membaca gambar (`.png`, `.jpg`, `.jpeg`, `.webp`, `.tif`, `.tiff`, `.bmp`, `.gif`),
install aplikasi OCR Tesseract di sistem:

```bash
sudo apt install tesseract-ocr tesseract-ocr-ind
```

Catatan: PDF hasil scan biasanya tidak punya teks tertanam. Ubah halaman PDF scan menjadi gambar,
lalu baca dengan `/file gambar.png ...`, atau jalankan OCR PDF di luar aplikasi terlebih dahulu.

## Konfigurasi

Edit `~/.config/ai-chat-cli/config.json`:

```json
{
  "provider": "ollama",
  "ollama": {
    "base_url": "http://127.0.0.1:11434",
    "model": "qwen2.5:1.5b"
  },
  "localai": {
    "base_url": "http://127.0.0.1:8080",
    "model": "gpt-3.5-turbo",
    "api_key": ""
  },
  "system_prompt": "Kamu adalah asisten AI yang ramah...",
  "temperature": 0.7,
  "show_thinking": true
}
```

Environment:

```bash
export AI_CHAT_PROVIDER=localai
```

## Prasyarat

- **Ollama**: `ollama serve` (biasanya sudah jalan) + model (`ollama pull qwen2.5:1.5b`)
- **LocalAI**: server di `http://127.0.0.1:8080` dengan endpoint OpenAI-compatible
