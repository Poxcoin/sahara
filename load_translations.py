"""
Load pre-translated product titles into the database.
"""
import sqlite3

DB_PATH = "data/sahara.db"

# Translations: (id, title_ua, title_en)
translations = [
    (129, "Асиметрична міні-сукня з круглим вирізом без рукавів", "Asymmetric Drape A-Line Sleeveless Mini Dress"),
    (130, "Блуза з довгим рукавом і V-подібним вирізом з воланом", "Viscose Blend Ruffled V-Neck Long Sleeve Blouse"),
    (131, "Жилет на гудзиках з V-подібним вирізом з вісконом", "V-Neck Viscose Blend Buttoned Sleeveless Vest"),
    (132, "Шифонова міні-сукня без рукавів з декольте", "Sleeveless Off-Shoulder Chiffon Mini Evening Dress"),
    (133, "Широкі прямі штани з поясом з тканини аеробін", "Aerobin Wide Leg Belted Long Straight Trousers"),
    (134, "Штани Cigarette з прямою штаниною та деталлю ременя", "Regular Waist Slim Fit Belted Cigarette Trousers"),
    (135, "Бавовняна міні-сукня без рукавів з воланами", "Sleeveless Round-Neck Cotton Tiered Ruffle Mini Dress"),
    (136, "Спортивні штани з широкою штаниною та кишенями", "Ribbed Wide Leg Drawstring Pocket Sweatpants"),
    (137, "Спортивний светр на блискавці з капюшоном", "Hooded Long Sleeve Zip-Up Seam Detail Sports Sweatshirt"),
    (138, "Штани Cigarette Slim Fit з кишенями", "Slim Fit Pocketed Regular Waist Cigarette Trousers"),
    (139, "Оверсайз футболка з круглим вирізом та принтом на спині", "Short Sleeve Printed Back Oversized Cotton T-Shirt"),
    (140, "Спортивні легінси Skinny Fit з високою талією", "High-Waist Skinny Fit Sports Leggings"),
    (141, "Кроп-топ без рукавів Slim Fit з деталлю рядка", "Seam Detail Slim Fit Sleeveless Crop T-Shirt"),
    (142, "Бавовняна блуза без рукавів Slim Fit", "Slim Fit Sleeveless Cotton Round-Neck Blouse"),
    (143, "Смугаста футболка Slim Fit з коміром поло", "Slim Fit Short Sleeve Striped Polo Neck Viscose T-Shirt"),
    (144, "Оверсайз спортивний светр з капюшоном з вісконом", "Viscose Blend Long Sleeve Hooded Oversized Sweatshirt"),
    (145, "Міні спідниця-шорти з вишивкою та зав'язкою", "Slim Fit Regular Waist Drawstring Embroidered Mini Sport Skort"),
    (146, "Футболка Slim Fit з коміром поло та фактурою", "Slim Fit Short Sleeve Textured Polo Neck T-Shirt"),
    (147, "Бавовняна футболка Slim Fit з круглим вирізом", "Cotton Short Sleeve Round-Neck Slim Fit Ribbed T-Shirt"),
    (148, "Широкі джинси з кишенями та декоративними каменями", "Cotton Buttoned Wide Leg Stone Detail Denim Jeans"),
    (149, "Облягаючий топ-атлет без рукавів з U-подібним вирізом", "Ribbed U-Neck Sleeveless Slim Fit Tank Top"),
    (150, "Широкі джинси з декоративними каменями на бавовні", "Regular Waist Stone Detail Cotton Wide Leg Denim Jeans"),
    (151, "Бавовняні спортивні штани з широкою штаниною", "Cotton Piped Wide Leg Knit Slit Sweatpants"),
    (152, "Міді-сукня з короткими рукавами та V-подібним вирізом", "Crepe Short Sleeve V-Neck Midi Dress"),
    (153, "Облягаючий топ-атлет без рукавів з модалом", "Slim Fit Boat Neck Modal Blend Sleeveless Tank Top"),
    (154, "Міді-сукня на бретелях з драпіруванням", "Draped Round Neck Strappy Midi Dress"),
    (155, "Бавовняні штани-кюлоти з кишенями", "Cotton Pocketed Regular Waist Culotte Jeans"),
    (156, "Бавовняна блуза без рукавів з човниковим вирізом", "Cotton Slim Fit Sleeveless Boat-Neck Blouse"),
    (157, "Кроп-блуза без рукавів Slim Fit з декольте", "Sleeveless Off-Shoulder Slim Fit Crop Blouse"),
    (158, "Прямі джинси з гудзиками та декоративними каменями", "Regular Waist Pocketed Buttoned Stone Detail Straight Fit Jeans"),
    (159, "Асиметрична бавовняна блуза без рукавів з човниковим вирізом", "Cotton Asymmetric Cut Sleeveless Boat-Neck Blouse"),
    (160, "Бавовняна блуза без рукавів Slim Fit", "Cotton Round-Neck Slim Fit Sleeveless Blouse"),
    (161, "Спортивні байкерські легінси Slim Fit з високою талією", "High-Waist Slim Fit Biker Sports Leggings"),
    (162, "Асиметрична блуза-бандо без рукавів зі зборками", "Strapless Sleeveless Slim Fit Ruched Asymmetric Blouse"),
    (163, "Бавовняна блуза без рукавів з круглим вирізом", "Cotton Ribbed Sleeveless Round-Neck Blouse"),
    (164, "Спортивний бюстгальтер без рукавів з V-подібним вирізом", "V-Neck Sleeveless Slim Fit Sports Bra"),
    (165, "Бавовняні міні-шорти з вишивкою та зав'язкою", "Cotton Embroidered Drawstring Relaxed Fit Mini Shorts"),
    (166, "Футболка з коміром поло та вишивкою на гудзиках", "Slim Fit Cotton Embroidered Short Sleeve Buttoned Polo T-Shirt"),
    (167, "Прямі джинси з високою талією та кишенями", "High-Waist Straight Leg Pocketed Cotton Denim Jeans"),
    (168, "Блуза без рукавів з відкритими плечима та поясом", "Scuba Slim Fit Belted Off-Shoulder Boat-Neck Sleeveless Blouse"),
    (169, "Базовий топ-атлет без рукавів з U-подібним вирізом", "U-Neck Sleeveless Slim Fit Basic Tank Top"),
]

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

for pid, ua, en in translations:
    c.execute(
        "UPDATE products SET title_ua=?, title_en=? WHERE id=?",
        (ua, en, pid),
    )

conn.commit()

# Verify
c.execute("SELECT COUNT(*) FROM products WHERE title_ua IS NOT NULL AND title_en IS NOT NULL")
count = c.fetchone()[0]
c.execute("SELECT id, title_ua, title_en FROM products ORDER BY id LIMIT 5")
samples = c.fetchall()

conn.close()

print(f"Updated {len(translations)} products.")
print(f"Products with translations in DB: {count}")
print("\nSample translations:")
for pid, ua, en in samples:
    print(f"  id={pid}: ua='{ua}' | en='{en}'")
