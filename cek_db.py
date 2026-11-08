# cek_db.py — Cek isi database Raudha
import sqlite3

conn = sqlite3.connect('data/raudha.db')
c = conn.cursor()

USER_ID = 472469108

print("=" * 60)
print(f"CEK DATABASE — USER {USER_ID}")
print("=" * 60)

# 1. Users config
print("\n[1] USERS_CONFIG")
c.execute("""SELECT user_id, nama_lengkap, role, status, lembaga_id,
                    tanggal_mulai_haul, baseline_awal, khumus_aktif
             FROM users_config WHERE user_id=?""", (USER_ID,))
row = c.fetchone()
if row:
    print(f"  user_id        : {row[0]}")
    print(f"  nama           : {row[1]}")
    print(f"  role           : {row[2]}")
    print(f"  status         : {row[3]}")
    print(f"  lembaga_id     : {row[4]}")
    print(f"  mulai_haul     : {row[5]}")
    print(f"  baseline_awal  : Rp {int(row[6] or 0):,}".replace(",", "."))
    print(f"  khumus_aktif   : {bool(row[7])}")
else:
    print("  ❌ User tidak ditemukan")

# 2. Jurnal
print("\n[2] JURNAL_SYARIAH (aktif)")
c.execute("""SELECT id, gaji, hadiah, pertanian_kg, benda_mewah,
                    temuan_laut_karun, simpanan_bmt_idr,
                    pengeluaran_rutin, pengeluaran_sekolah,
                    pengeluaran_utang, pengeluaran_sedekah, tgl
             FROM jurnal_syariah
             WHERE user_id=? AND COALESCE(is_active,1)=1
             ORDER BY id DESC""", (USER_ID,))
rows = c.fetchall()
if rows:
    total_masuk = 0
    total_keluar = 0
    for r in rows:
        masuk = (r[1] or 0) + (r[2] or 0) + (r[4] or 0) + (r[5] or 0) + (r[6] or 0)
        keluar = (r[7] or 0) + (r[8] or 0) + (r[9] or 0) + (r[10] or 0)
        total_masuk += masuk
        total_keluar += keluar
        print(f"  #{r[0]} | {r[11]} | masuk: Rp {int(masuk):,} | keluar: Rp {int(keluar):,}".replace(",", "."))
    print(f"  ─────────────────────────────────────")
    print(f"  TOTAL masuk  : Rp {int(total_masuk):,}".replace(",", "."))
    print(f"  TOTAL keluar : Rp {int(total_keluar):,}".replace(",", "."))
    print(f"  Netto        : Rp {int(total_masuk - total_keluar):,}".replace(",", "."))
else:
    print("  (kosong — belum ada input)")

# 3. Pembayaran
print("\n[3] RENCANA_PEMBAYARAN")
c.execute("""SELECT status, COUNT(*), SUM(nominal)
             FROM rencana_pembayaran WHERE user_id=?
             GROUP BY status""", (USER_ID,))
rows = c.fetchall()
if rows:
    for r in rows:
        print(f"  {r[0]:15s}: {r[1]} transaksi, Rp {int(r[2] or 0):,}".replace(",", "."))
    c.execute("""SELECT COUNT(*), SUM(nominal) FROM rencana_pembayaran
                 WHERE user_id=?""", (USER_ID,))
    total = c.fetchone()
    print(f"  TOTAL          : {total[0]} transaksi, Rp {int(total[1] or 0):,}".replace(",", "."))
else:
    print("  (kosong)")

# 4. Tagihan
print("\n[4] TAGIHAN")
c.execute("""SELECT status, COUNT(*), SUM(nominal)
             FROM tagihan WHERE user_id=?
             GROUP BY status""", (USER_ID,))
rows = c.fetchall()
if rows:
    for r in rows:
        print(f"  {r[0]:15s}: {r[1]} tagihan, Rp {int(r[2] or 0):,}".replace(",", "."))
else:
    print("  (kosong)")

# 5. Lembaga (kalau admin)
print("\n[5] LEMBAGA_AMIL (jika admin)")
c.execute("""SELECT id, nama, jenis, status FROM lembaga_amil WHERE id IN
             (SELECT lembaga_id FROM users_config WHERE user_id=?)""", (USER_ID,))
rows = c.fetchall()
if rows:
    for r in rows:
        print(f"  #{r[0]} {r[1]} ({r[2]}) — {r[3]}")
else:
    print("  (bukan admin lembaga)")

print("\n" + "=" * 60)
conn.close()