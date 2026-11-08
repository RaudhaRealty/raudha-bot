# test_panen.py
import asyncio
import sqlite3
from unittest.mock import AsyncMock, MagicMock
import bot

async def main():
    print("=" * 60)
    print("TEST HANDLER handle_panen_confirm")
    print("=" * 60)
    
    # Simulasi context.user_data
    context = MagicMock()
    context.user_data = {
        'panen_pohon_id': 1,
        'panen_pohon_info': 'Kurma Hibrida #1',
        'panen_data_temp': {
            'hasil_kg': 4,
            'harga_per_kg': 50000,
            'total': 200000,
            'bagi_masjid': 140000,
            'bagi_perawatan': 40000,
            'bagi_raudha': 20000,
            'catatan': 'Test via handler simulation'
        }
    }
    
    # Simulasi query callback
    query = MagicMock()
    query.data = 'panen_confirm'
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    
    # Simulasi update
    update = MagicMock()
    update.callback_query = query
    
    print("Memanggil handle_panen_confirm...")
    try:
        await bot.handle_panen_confirm(update, context)
        print("✅ Handler selesai tanpa error")
    except Exception as e:
        print(f"❌ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Cek DB
    print()
    print("=" * 60)
    print("DATA POHON_PANEN (pohon_id=1)")
    print("=" * 60)
    c = sqlite3.connect('data/raudha.db').cursor()
    c.execute("""SELECT id, tanggal_panen, hasil_kg, hasil_nominal, 
                        pembagian_masjid, catatan 
                 FROM pohon_panen WHERE pohon_id=1 
                 ORDER BY id DESC LIMIT 5""")
    rows = c.fetchall()
    if not rows:
        print("❌ TIDAK ADA DATA")
    else:
        print(f"Total: {len(rows)} baris")
        for r in rows:
            print(f"  {r}")
    
    # Cek callback log (apakah safe_edit dipanggil)
    print()
    print("=" * 60)
    print("CALLBACK LOG")
    print("=" * 60)
    print(f"query.answer calls: {query.answer.call_count}")
    print(f"query.edit_message_text calls: {query.edit_message_text.call_count}")
    
    if query.edit_message_text.call_count > 0:
        # Ambil pesan terakhir yang di-edit
        args, kwargs = query.edit_message_text.call_args
        if args:
            print(f"Pesan edit: {args[0][:200] if args else '-'}...")
        elif 'text' in kwargs:
            print(f"Pesan edit: {kwargs['text'][:200]}...")


if __name__ == '__main__':
    asyncio.run(main())