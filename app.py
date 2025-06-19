from flask import Flask, request, render_template, jsonify, flash, redirect, url_for
import pandas as pd
from itertools import combinations
import os
import logging
from werkzeug.utils import secure_filename
import json
import plotly.graph_objs as go
import plotly.utils

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Gerçek projede güçlü bir key kullanın
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB limit

# Logging ayarları
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'xlsx', 'xls'}
UPLOAD_FOLDER = 'uploads'

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_dataframe(df):
    """DataFrame'in gerekli sütunları içerip içermediğini kontrol eder"""
    required_columns = ['Numara', 'Ürün Grubu']
    missing_columns = [col for col in required_columns if col not in df.columns]
    
    if missing_columns:
        return False, f"Eksik sütunlar: {', '.join(missing_columns)}"
    
    if df.empty:
        return False, "Dosya boş"
    
    return True, "OK"

def create_chart(data, chart_type, title):
    """Plotly grafikleri oluşturur"""
    try:
        if chart_type == 'bar':
            fig = go.Figure(data=[
                go.Bar(x=data.index, y=data.values, 
                      marker_color='rgba(102, 126, 234, 0.8)')
            ])
            fig.update_layout(
                title=title,
                xaxis_title="Ürün Grubu",
                yaxis_title="Satış Sayısı",
                template="plotly_white"
            )
        elif chart_type == 'pie':
            fig = go.Figure(data=[
                go.Pie(labels=data.index, values=data.values, hole=0.3)
            ])
            fig.update_layout(title=title)
        
        return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
    except Exception as e:
        logger.error(f"Grafik oluşturma hatası: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        # Dosya kontrolü
        if 'file' not in request.files:
            flash('Dosya seçilmedi!', 'error')
            return redirect(url_for('index'))
        
        file = request.files['file']
        if file.filename == '':
            flash('Dosya seçilmedi!', 'error')
            return redirect(url_for('index'))
        
        if not allowed_file(file.filename):
            flash('Sadece Excel dosyaları (.xlsx, .xls) desteklenir!', 'error')
            return redirect(url_for('index'))
        
        # Analiz parametreleri
        analysis_type = request.form.get('analysis')
        urun1 = request.form.get('urun1', '').lower().strip()
        urun2 = request.form.get('urun2', '').lower().strip()
        
        # Dosyayı oku
        try:
            df = pd.read_excel(file)
            logger.info(f"Dosya okundu: {df.shape[0]} satır, {df.shape[1]} sütun")
        except Exception as e:
            flash(f'Dosya okuma hatası: {str(e)}', 'error')
            return redirect(url_for('index'))
        
        # DataFrame validasyonu
        is_valid, error_msg = validate_dataframe(df)
        if not is_valid:
            flash(f'Veri hatası: {error_msg}', 'error')
            return redirect(url_for('index'))
        
        # Veri temizleme
        df = df.dropna(subset=['Numara'])
        df['Ürün Grubu'] = df['Ürün Grubu'].astype(str).str.lower().str.strip()
        df['Numara'] = df['Numara'].astype(str)
        
        result_data = {}
        chart_json = None
        
        # Analiz türüne göre işlem
        if analysis_type == 'sales':
            sales_data = df['Ürün Grubu'].value_counts()
            result_data = {
                'type': 'sales',
                'title': 'Ürün Satış Analizi',
                'data': sales_data.to_dict(),
                'total_products': len(sales_data),
                'total_sales': sales_data.sum()
            }
            chart_json = create_chart(sales_data.head(10), 'bar', 'Top 10 En Çok Satan Ürünler')
            
        elif analysis_type == 'lift':
            if not urun1 or not urun2:
                flash('Lift analizi için her iki ürün adını da giriniz!', 'error')
                return redirect(url_for('index'))
            
            df['Urun1'] = df['Ürün Grubu'] == urun1
            df['Urun2'] = df['Ürün Grubu'] == urun2
            
            pivot = df.groupby('Numara').agg({'Urun1': 'max', 'Urun2': 'max'}).reset_index()
            total = pivot.shape[0]
            a = pivot['Urun1'].sum()
            b = pivot['Urun2'].sum()
            ab = pivot[(pivot['Urun1']) & (pivot['Urun2'])].shape[0]
            
            if total == 0:
                flash('Analiz için yeterli veri yok!', 'error')
                return redirect(url_for('index'))
            
            p_a = a / total
            p_b = b / total
            p_ab = ab / total
            
            lift = round(p_ab / (p_a * p_b), 2) if p_a * p_b > 0 else 0
            confidence = round(p_ab / p_a, 2) if p_a > 0 else 0
            support = round(p_ab, 2)
            
            result_data = {
                'type': 'lift',
                'title': f'Lift Analizi: {urun1.title()} & {urun2.title()}',
                'lift': lift,
                'confidence': confidence,
                'support': support,
                'together_sales': ab,
                'product1_sales': a,
                'product2_sales': b,
                'total_customers': total,
                'interpretation': get_lift_interpretation(lift)
            }
            
        elif analysis_type == 'pair':
            basket = df.groupby('Numara')['Ürün Grubu'].apply(set)
            pair_counts = {}
            
            for urunler in basket:
                if len(urunler) >= 2:
                    for u1, u2 in combinations(sorted(urunler), 2):
                        pair = (u1, u2)
                        pair_counts[pair] = pair_counts.get(pair, 0) + 1
            
            sorted_pairs = sorted(pair_counts.items(), key=lambda x: x[1], reverse=True)[:20]
            
            result_data = {
                'type': 'pair',
                'title': 'En Çok Birlikte Satılan Ürün Çiftleri',
                'pairs': [{'products': f"{p[0].title()} + {p[1].title()}", 'count': c} 
                         for (p, c) in sorted_pairs],
                'total_pairs': len(pair_counts)
            }
            
        elif analysis_type == 'time':
            if 'Tarih' not in df.columns:
                flash('Zaman analizi için Tarih sütunu gerekli!', 'error')
                return redirect(url_for('index'))
            
            df['Tarih'] = pd.to_datetime(df['Tarih'], errors='coerce')
            df = df.dropna(subset=['Tarih'])
            df['Ay'] = df['Tarih'].dt.to_period("M")
            
            time_data = df.groupby('Ay').size()
            
            result_data = {
                'type': 'time',
                'title': 'Aylık Satış Trendi',
                'data': {str(k): v for k, v in time_data.to_dict().items()},
                'total_months': len(time_data)
            }
            
        elif analysis_type == 'customer':
            urun_ade = df.groupby('Numara').size()
            urun_tur = df.groupby('Numara')['Ürün Grubu'].nunique()
            
            customer_stats = pd.DataFrame({
                "Toplam Ürün": urun_ade, 
                "Ürün Çeşidi": urun_tur
            })
            
            result_data = {
                'type': 'customer',
                'title': 'Müşteri Analizi',
                'avg_products_per_customer': round(customer_stats['Toplam Ürün'].mean(), 2),
                'avg_variety_per_customer': round(customer_stats['Ürün Çeşidi'].mean(), 2),
                'total_customers': len(customer_stats),
                'max_products': customer_stats['Toplam Ürün'].max(),
                'max_variety': customer_stats['Ürün Çeşidi'].max()
            }
            
        else:
            flash('Geçersiz analiz türü!', 'error')
            return redirect(url_for('index'))
        
        return render_template('results.html', 
                             result=result_data, 
                             chart=chart_json)
        
    except Exception as e:
        logger.error(f"Analiz hatası: {e}")
        flash(f'Analiz sırasında hata oluştu: {str(e)}', 'error')
        return redirect(url_for('index'))

def get_lift_interpretation(lift):
    """Lift değerini yorumlar"""
    if lift is None or lift == 0:
        return "Hesaplanamadı"
    elif lift > 1.5:
        return "Çok güçlü pozitif korelasyon"
    elif lift > 1.2:
        return "Güçlü pozitif korelasyon"
    elif lift > 1.0:
        return "Zayıf pozitif korelasyon"
    elif lift == 1.0:
        return "Bağımsız ürünler"
    else:
        return "Negatif korelasyon"

@app.errorhandler(413)
def too_large(e):
    flash('Dosya boyutu çok büyük! Maksimum 16MB', 'error')
    return redirect(url_for('index'))

@app.errorhandler(500)
def internal_error(e):
    flash('Sunucu hatası oluştu!', 'error')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
