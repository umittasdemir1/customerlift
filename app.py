from flask import Flask, request, render_template
import pandas as pd
from itertools import combinations

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    file = request.files['file']
    analysis_type = request.form['analysis']
    urun1 = request.form.get('urun1', '').lower().strip()
    urun2 = request.form.get('urun2', '').lower().strip()
    df = pd.read_excel(file)
    df = df.dropna(subset=['Numara'])
    df['Ürün Grubu'] = df['Ürün Grubu'].astype(str).str.lower().str.strip()
    df['Numara'] = df['Numara'].astype(str)

    result = ""

    if analysis_type == 'sales':
        result = df['Ürün Grubu'].value_counts().to_frame().to_html()
    elif analysis_type == 'lift':
        df['Urun1'] = df['Ürün Grubu'] == urun1
        df['Urun2'] = df['Ürün Grubu'] == urun2
        pivot = df.groupby('Numara').agg({'Urun1': 'max', 'Urun2': 'max'}).reset_index()
        total = pivot.shape[0]
        a = pivot['Urun1'].sum()
        b = pivot['Urun2'].sum()
        ab = pivot[(pivot['Urun1']) & (pivot['Urun2'])].shape[0]
        p_a = a / total
        p_b = b / total
        p_ab = ab / total
        lift = round(p_ab / (p_a * p_b), 2) if p_a * p_b > 0 else None
        result = f"<p><b>Lift:</b> {lift} - Birlikte satış: {ab}</p>"
    elif analysis_type == 'pair':
        basket = df.groupby('Numara')['Ürün Grubu'].apply(set)
        pair_counts = {}
        for urunler in basket:
            for u1, u2 in combinations(sorted(urunler), 2):
                pair = (u1, u2)
                pair_counts[pair] = pair_counts.get(pair, 0) + 1
        sorted_pairs = sorted(pair_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        result = "<ul>" + "".join([f"<li>{p[0]} + {p[1]} = {c}</li>" for (p, c) in sorted_pairs]) + "</ul>"
    elif analysis_type == 'time':
        if 'Tarih' in df.columns:
            df['Tarih'] = pd.to_datetime(df['Tarih'], errors='coerce')
            df['Ay'] = df['Tarih'].dt.to_period("M")
            result = df.groupby(['Ay', 'Ürün Grubu']).size().unstack(fill_value=0).to_html()
        else:
            result = "<p>Tarih sütunu bulunamadı.</p>"
    elif analysis_type == 'customer':
        urun_ade = df.groupby('Numara').size()
        urun_tur = df.groupby('Numara')['Ürün Grubu'].nunique()
        result = pd.DataFrame({"Toplam Ürün Adedi": urun_ade, "Ürün Çeşidi": urun_tur}).to_html()
    else:
        result = "<p>Geçersiz analiz türü</p>"

    return result

if __name__ == '__main__':
    app.run(debug=True)
