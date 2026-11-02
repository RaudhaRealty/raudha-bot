# modul_keuangan/kalkulator_syariah.py
import datetime

class KalkulatorSyariah:
    def __init__(self, harga_emas_per_gram=1500000, harga_perak_per_gram=18000):
        """
        Harga emas & perak idealnya ditarik dari API, 
        namun disediakan nilai default sebagai fallback.
        """
        self.harga_emas = harga_emas_per_gram
        self.harga_perak = harga_perak_per_gram
        
        # Nisab Standar Fikih
        self.nisab_emas_gram = 85
        self.nisab_perak_gram = 595
        self.nisab_padi_kg = 653  # 5 Wasaq
        
    def hitung_zakat_maal_dan_simpanan(self, data_harta):
        """
        Menghitung Zakat Maal atas simpanan, emas, perak, perhiasan, 
        dan barang antik/seni/mewah (Jam tangan, lukisan, ukiran).
        """
        total_nilai_harta = 0
        
        # 1. Akumulasi Logam Mulia & Benda Berharga
        total_nilai_harta += data_harta.get("uang_simpanan", 0)
        total_nilai_harta += data_harta.get("emas_gram", 0) * self.harga_emas
        total_nilai_harta += data_harta.get("perak_gram", 0) * self.harga_perak
        total_nilai_harta += data_harta.get("perhiasan_nilai", 0)
        total_nilai_harta += data_harta.get("benda_mewah_nilai", 0)  # Jam tangan mewah, lukisan, ukiran
        
        nisab_maal_rupiah = self.nisab_emas_gram * self.harga_emas
        wajib_zakat = total_nilai_harta >= nisab_maal_rupiah
        
        zakat_dibayar = (total_nilai_harta * 0.025) if wajib_zakat else 0
        
        return {
            "total_harta_maal": total_nilai_harta,
            "nisab_maal_rupiah": nisab_maal_rupiah,
            "wajib_zakat": wajib_zakat,
            "zakat_maal_nominal": zakat_dibayar
        }

    def hitung_zakat_pendapatan(self, gaji, honor, hadiah):
        """Zakat Profesi / Pendapatan disetarakan nisab emas 85 gram per tahun (atau bulanan)"""
        total_pendapatan = gaji + honor + hadiah
        nisab_bulanan_rupiah = (self.nisab_emas_gram * self.harga_emas) / 12
        
        wajib_zakat = total_pendapatan >= nisab_bulanan_rupiah
        zakat_nominal = (total_pendapatan * 0.025) if wajib_zakat else 0
        
        return {
            "total_pendapatan": total_pendapatan,
            "wajib_zakat_profesi": wajib_zakat,
            "zakat_profesi_nominal": zakat_nominal
        }

    def hitung_zakat_bumi(self, hasil_panen_kg, jenis_pengairan):
        """
        Zakat Hasil Bumi (Pertanian):
        - Tadah hujan / Alami: 10%
        - Irigasi (Mengeluarkan biaya): 5%
        """
        wajib_zakat = hasil_panen_kg >= self.nisab_padi_kg
        if not wajib_zakat:
            return {"wajib_zakat_bumi": False, "zakat_bumi_kg": 0}
            
        tarif = 0.10 if jenis_pengairan == "tadah_hujan" else 0.05
        zakat_kg = hasil_panen_kg * tarif
        
        return {
            "wajib_zakat_bumi": True,
            "tarif_persen": tarif * 100,
            "zakat_bumi_kg": zakat_kg
        }

    def hitung_khumus_dan_rikaz(self, kategori, nilai_temuan):
        """
        Khumus (1/20 atau 20%):
        Berlaku untuk Harta Karun (Rikaz), Hasil Penyelaman (Laut), atau keuntungan usaha/surplus yang belum dizakati.
        """
        # Rikaz dan Ma'din tidak mensyaratkan Haal/Haul dalam mayoritas fikih, langsung dipotong 20%
        khumus_nominal = nilai_temuan * 0.20
        return {
            "kategori": kategori,
            "nilai_total": nilai_temuan,
            "khumus_nominal": khumus_nominal
        }
