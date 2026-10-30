# Hawk Strike Barbershop — starter MVP

Loyiha ikki qismdan iborat:
- `/` — Instagram va boshqa ijtimoiy tarmoqlardan ochiladigan ommaviy sahifa: sartaroshlar, xizmatlar/narxlar, lokatsiya va zakas tugmasi.
- `/app` — Telegram Mini App bandlov sahifasi. URL orqali `?service=ID` berilsa, oldindan tanlangan xizmat saqlanadi.

## Ishga tushirish
1. Python 3.10+ o‘rnating.
2. `pip install -r requirements.txt`
3. `.env.example` faylidan `.env` yarating va maxfiy qiymatlarni to‘ldiring.
4. `python app.py` — lokal tekshiruv uchun.
5. Telegram bot uchun `python bot.py`.
6. Telegram Mini App uchun `APP_URL` ommaviy HTTPS manzil bo‘lishi va `/app` bilan tugashi kerak.

## Hozirgi namunaviy sozlamalar
- Ish vaqti: 09:00–23:00.
- Bandlov boshlanishlari: har 1 soatda (09:00 ... 22:00).
- Namunaviy sartaroshlar: Aziz, Doni, Ali.
- Demo loginlar: `aziz`, `doni`, `ali`; dastlabki parol `change-me`.
- Namunaviy xizmatlar va narxlar: koddagi `init_db()` ichida.
- Ommaviy sahifa manzili `.env` dagi `SHOP_ADDRESS` va `MAPS_URL` orqali beriladi.

## Muhim
Bu boshlang‘ich MVP, ommaviy ishga tushirishga tayyor yakuniy mahsulot emas.
- Barcha demo parollarni almashtiring; `FLASK_SECRET`, `BOT_TOKEN`, `ADMIN_PASSWORD` ni xavfsiz qiymatlarga o‘zgartiring.
- Hozirgi versiyada Telegram `initData` tekshiruvi helperi mavjud, ammo bandlov API'sida majburiy qilib qo‘yilmagan. Public deploydan oldin qat’iy tekshiruv va autentifikatsiya qo‘shish zarur.
- Eslatma yuborish (uchrashuvdan 1 soat oldin), profil rasmini yuklash, sartarosh/xizmatlarni administrator panelidan boshqarish, sartaroshning o‘z profilini tahrirlashi hali to‘liq amalga oshirilmagan.
- Hozircha sartarosh rasmlari uchun haqiqiy upload/admin boshqaruvi yo‘q; landing sahifada boshlang‘ich avatar ko‘rsatiladi.
- Booking slotlari 1 soatlik va 09:00–22:00 boshlanish vaqtlariga o‘rnatilgan. Xizmat davomiyligi bo‘yicha overlap tekshiruvi hali qo‘shilmagan.
- `ADMIN_CHAT_ID` bildirishnomalari admin botni avval ishga tushirganidan keyin ishlaydi.
- Manzil va xarita havolasini haqiqiy ma’lumot bilan `.env` orqali kiriting.

## Demo rollar
- Admin: `.env` dagi `ADMIN_USER` va `ADMIN_PASSWORD`.
- Sartaroshlar: `aziz`, `doni`, `ali` (demo parolni albatta yangilang).
