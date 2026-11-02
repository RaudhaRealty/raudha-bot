# modul_validasi.py
import re
from datetime import datetime, date

BATAS_MAKS = {
    "rupiah": 100_000_000_000,     # 100 miliar — di atas ini curiga
    "kg":     1_000_000,           # 1000 ton panen
    "ekor":   10_000,              # ternak
    "gram":   100_000,             # logam mulia
}

VALID_ENUM = {
    "irigasi":      {"alami", "berbiaya"},
    "jenis_hewan":  {"unta", "sapi", "kambing"},
    "grazing":      {"padang", "kandang"},
    "simpanan":     {"uang","emas_gram","perak_gram","perhiasan_gram"},
    "khumus_jenis": {"harta_karun","tambang","selam_laut","rampasan","fai"},
    "kategori_keluar": {"makan","tempat_tinggal","kesehatan","pendidikan",
                        "transport","orang_tanggungan","hutang","lainnya"},
    "halal":        {"halal","bercampur_haram"},
}

class ValidationError(Exception):
    def __init__(self, errors): self.errors = errors
    def __str__(self): return "; ".join(self.errors)


def cek_nominal(nama, nilai, maks=None, boleh_nol=False):
    errs = []
    if nilai is None or nilai == "":
        errs.append(f"{nama}: wajib diisi"); return errs
    try:
        v = float(nilai)
    except (TypeError, ValueError):
        errs.append(f"{nama}: bukan angka ({nilai!r})"); return errs

    if v < 0:
        errs.append(f"{nama}: tidak boleh negatif")
    if not boleh_nol and v == 0:
        errs.append(f"{nama}: harus lebih dari 0")
    if v != int(v) and abs(v) < 1 and v != 0:
        errs.append(f"{nama}: terlalu kecil, mungkin salah ketik desimal")
    limit = maks or BATAS_MAKS["rupiah"]
    if v > limit:
        errs.append(f"{nama}: Rp{v:,.0f} melewati batas wajar, periksa lagi")
    # Deteksi pola suspicious: angka bulat kelipatan 10^7 ke atas (indikasi extra zero)
    if v >= 10_000_000 and v % 10_000_000 == 0 and v > 500_000_000:
        errs.append(f"{nama}: nilai sangat besar, konfirmasi ulang jumlah nolnya")
    return errs


def cek_tanggal(nama, tgl_str, tidak_boleh_depan=True):
    if not tgl_str: return []
    try:
        d = datetime.strptime(tgl_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return [f"{nama}: format tanggal salah (pakai YYYY-MM-DD)"]
    errs = []
    if tidak_boleh_depan and d > date.today():
        errs.append(f"{nama}: tanggal di masa depan tidak diterima")
    if d < date(1980, 1, 1):
        errs.append(f"{nama}: tanggal terlalu lama, periksa tahunnya")
    return errs


def cek_enum(nama, nilai, kunci):
    if nilai not in VALID_ENUM[kunci]:
        return [f"{nama}: '{nilai}' tidak valid, pilih salah satu {sorted(VALID_ENUM[kunci])}"]
    return []


def cek_user(user_id):
    if not isinstance(user_id, int) or user_id <= 0:
        return ["user_id tidak valid"]
    return []


# ====== VALIDATOR PER TABEL ======
def validasi_pendapatan(d):
    e  = cek_user(d.get("user_id"))
    e += cek_nominal("Jumlah", d.get("jumlah"))
    e += cek_nominal("Ongkos produksi", d.get("ongkos_produksi", 0), boleh_nol=True)
    e += cek_enum("Status sumber", d.get("sumber_halal","halal"), "halal")
    e += cek_tanggal("Tanggal terima", d.get("tgl"))
    jml = float(d.get("jumlah") or 0); ong = float(d.get("ongkos_produksi") or 0)
    if ong > jml:
        e.append("Ongkos produksi melebihi pendapatan — periksa kembali")
    return e


def validasi_pertanian(d):
    e  = cek_user(d.get("user_id"))
    e += cek_nominal("Hasil panen (kg)", d.get("hasil_kg"), BATAS_MAKS["kg"])
    e += cek_nominal("Harga per kg", d.get("harga_per_kg"), boleh_nol=True)
    e += cek_nominal("Biaya panen", d.get("biaya_panen", 0), boleh_nol=True)
    e += cek_enum("Irigasi", d.get("irigasi","alami"), "irigasi")
    e += cek_tanggal("Tanggal panen", d.get("tgl_panen"))
    kg = float(d.get("hasil_kg") or 0)
    if 0 < kg < 653:
        e.append(f"WASPADA: {kg} kg masih di bawah nisab 653 kg (tetap boleh disimpan untuk akumulasi)")
    return e


def validasi_peternakan(d):
    e  = cek_user(d.get("user_id"))
    e += cek_enum("Jenis hewan", d.get("jenis"), "jenis_hewan")
    e += cek_enum("Sistem", d.get("sistem_grazing","padang"), "grazing")
    e += cek_nominal("Jumlah ekor", d.get("jumlah"), BATAS_MAKS["ekor"])
    e += cek_tanggal("Mulai haul", d.get("tgl_mulai_haul"))
    n = d.get("jumlah")
    if n is not None and float(n) != int(float(n)):
        e.append("Jumlah hewan harus bilangan bulat (tidak ada 2,5 kambing)")
    return e


def validasi_simpanan(d):
    e  = cek_user(d.get("user_id"))
    e += cek_enum("Jenis harta", d.get("jenis"), "simpanan")
    e += cek_nominal("Jumlah uang", d.get("jumlah_uang", 0), boleh_nol=True)
    e += cek_nominal("Jumlah gram", d.get("jumlah_gram", 0), BATAS_MAKS["gram"], True)
    e += cek_tanggal("Mulai haul", d.get("tgl_mulai_haul"))
    if float(d.get("jumlah_uang") or 0) == 0 and float(d.get("jumlah_gram") or 0) == 0:
        e.append("Isi minimal salah satu: jumlah uang atau gram")
    if d.get("jenis") == "uang" and float(d.get("jumlah_gram") or 0) > 0:
        e.append("Jenis 'uang' tidak bisa punya kolom gram terisi")
    return e


def validasi_khumus_khusus(d):
    e  = cek_user(d.get("user_id"))
    e += cek_enum("Jenis khumus", d.get("jenis"), "khumus_jenis")
    e += cek_nominal("Jumlah", d.get("jumlah"))
    e += cek_nominal("Biaya perolehan", d.get("biaya_perolehan", 0), boleh_nol=True)
    e += cek_tanggal("Tanggal", d.get("tgl"))
    if float(d.get("biaya_perolehan") or 0) > float(d.get("jumlah") or 0):
        e.append("Biaya perolehan melebihi nilai harta")
    return e


def validasi_pengeluaran(d):
    e  = cek_user(d.get("user_id"))
    e += cek_nominal("Jumlah", d.get("jumlah"))
    e += cek_enum("Kategori", d.get("kategori"), "kategori_keluar")
    e += cek_tanggal("Tanggal", d.get("tgl"))
    return e


VALIDATOR = {
    "pendapatan":    validasi_pendapatan,
    "pertanian":     validasi_pertanian,
    "peternakan":    validasi_peternakan,
    "simpanan":      validasi_simpanan,
    "khumus_khusus": validasi_khumus_khusus,
    "pengeluaran":   validasi_pengeluaran,
}