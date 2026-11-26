# Design Brief: Inventory API 

Author: `Rian Prasetya Munaji | 24/545573/TK/60702` · Tanggal: 26 November 2026

## 1. Use case

Layanan inventaris untuk mencatat barang (misalnya peralatan laboratorium): menambah barang, melihat datanya, mengubah jumlah
stok atau lokasinya, dan menghapusnya. Penggunanya tim kecil yang butuh daftar stok bersama yang bisa diakses lewat HTTP tanpa
mengelola server.

## 2. Track yang dipilih

**Track C (Serverless)** dengan **elemen Track B (Docker)**. Satu fungsi Lambda Python 3.12 melayani semua endpoint CRUD dan
menyimpan data di layanan penyimpanan terkelola. Dua layanan direncanakan: `inventory-api` (dibangun pada tahap ini) dan
`stock-alert` (hanya rencana: notifikasi saat stok di bawah batas minimum). Serverless dipilih karena tidak ada instance atau
database yang berbiaya saat tidak dipakai.

## 3. Arsitektur

Diagram: `docs/architecture.png`.

| Peran | Desain awal | Yang dipakai di sandbox | Alasan penggantian |
| --- | --- | --- | --- |
| Pintu masuk HTTPS | API Gateway (HTTP API) | Lambda Function URL | `apigateway:POST` ditolak |
| Komputasi | Lambda (container image) | Lambda (paket zip) | ECR tidak tersedia |
| Penyimpanan | DynamoDB | Amazon S3 (objek JSON per barang) | `dynamodb:CreateTable` ditolak |
| Registry image | ECR | Docker image di-build dan diuji di laptop | `ecr:CreateRepository` ditolak |

Lingkungan: AWS Academy Cloud Foundations Sandbox, region us-east-1. Arsitektur tetap sama: pintu masuk HTTPS → Lambda →
penyimpanan. Kode mendukung DynamoDB (`TABLE_NAME`) dan S3 (`BUCKET_NAME`), sehingga bisa kembali ke desain awal tanpa
mengubah logika aplikasi.

- **Alur permintaan:** klien → HTTPS → Lambda Function URL → Lambda `inventory-api` → S3 `items/<item_id>.json`.
- **Alur deploy:** laptop (WSL) → zip `app/` → Lambda; Docker image di-build dari `Dockerfile` dan diuji lokal.
- **Log:** Lambda menulis ke CloudWatch Logs.
- **IAM:** Lambda berjalan dengan **LabRole** bawaan sandbox, yang memberi akses ke S3 dan CloudWatch Logs.
- **Jaringan:** Lambda di luar VPC; klien hanya masuk lewat HTTPS Function URL. Tidak ada NAT Gateway atau load balancer.

## 4. Entitas data

`item`, kunci `item_id` (string, UUID).

| Field | Tipe | Keterangan |
| --- | --- | --- |
| item_id | string | dibuat otomatis |
| name | string | wajib |
| category | string | opsional |
| quantity | integer | >= 0 |
| location | string | opsional |
| min_stock | integer | >= 0 |
| updated_at | string | ISO 8601 UTC |

## 5. Endpoint CRUD

| Operasi | Metode dan path | Berhasil | Gagal |
| --- | --- | --- | --- |
| Create | POST /items | 201 | 400 |
| Read | GET /items/{item_id} | 200 | 404 |
| Update | PUT /items/{item_id} | 200 | 400, 404 |
| Delete | DELETE /items/{item_id} | 200 | 404 |

`GET /items` (daftar) adalah endpoint tambahan.

## 6. Keamanan

- Peran eksekusi: LabRole (peran IAM baru tidak bisa dibuat di sandbox).
- Hanya HTTPS; input divalidasi (nama wajib, bilangan bulat tidak negatif, panjang teks dibatasi).
- Bucket S3 tidak publik; kredensial tidak pernah di-commit (`.gitignore`).
- Keterbatasan: Function URL memakai auth type `NONE` pada tahap ini. Autentikasi (`AWS_IAM`, atau API key/authorizer bila
  API Gateway tersedia) adalah pengembangan berikutnya.

## 7. Rencana budget

Hanya layanan berbayar per pemakaian (Lambda, Function URL, S3). Sandbox menghapus semua resource di akhir sesi, sehingga
tidak ada biaya yang tertinggal. Yang sengaja dihindari: EC2 yang menyala terus, RDS, NAT Gateway, load balancer.

## 8. Deployment dan bukti

Langkah dan perintah yang dijalankan ada di `docs/deployment-plan.md`. Hasil uji `scripts/smoke-test.sh` terhadap Function URL:
201, 200, 200, 200, 200, 404, 400 (sesuai harapan). Bukti di `evidence/`: penolakan layanan, bucket S3, konfigurasi Lambda
(LabRole), Function URL, output smoke test, dan uji Docker lokal.

## 9. Risiko dan keterbatasan

- Sandbox membatasi layanan; tiga layanan desain awal diganti seperti tabel di bagian 3.
- Sandbox menghapus resource di akhir sesi, sehingga URL API tidak aktif setelah sesi berakhir; screenshot menjadi bukti.
- S3 tidak mendukung query seperti DynamoDB; `GET /items` membaca semua objek, cukup untuk skala kecil tetapi perlu DynamoDB
  untuk data besar.