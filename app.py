from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime
import os
from sqlalchemy import func
import barcode
from barcode.writer import ImageWriter
from io import BytesIO
import random
from PIL import Image
import argparse
from werkzeug.security import generate_password_hash, check_password_hash

# VAT Configuration for Saudi Arabia
VAT_RATE = 0.15  # 15% VAT rate

def calculate_vat(amount):
    """Calculate VAT amount for a given price"""
    return amount * VAT_RATE

def calculate_price_with_vat(price_without_vat):
    """Calculate price including VAT"""
    return price_without_vat * (1 + VAT_RATE)

def calculate_price_without_vat(price_with_vat):
    """Calculate price excluding VAT"""
    return price_with_vat / (1 + VAT_RATE)

def generate_invoice_number():
    """Generate unique invoice number"""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_suffix = random.randint(1000, 9999)
    return f"INV-{timestamp}-{random_suffix}"



app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///phone_shop.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

class Phone(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    condition = db.Column(db.String(20), nullable=False)  # new or used
    purchase_price = db.Column(db.Float, nullable=False)  # سعر الشراء (بدون ضريبة)
    selling_price = db.Column(db.Float, nullable=False)   # سعر البيع (بدون ضريبة)
    purchase_price_with_vat = db.Column(db.Float, nullable=False)  # سعر الشراء (مع ضريبة)
    selling_price_with_vat = db.Column(db.Float, nullable=False)   # سعر البيع (مع ضريبة)
    serial_number = db.Column(db.String(100), unique=True, nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=False)  # New field for phone number
    barcode_path = db.Column(db.String(200))  # New field for barcode image path
    description = db.Column(db.Text)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    warranty = db.Column(db.Integer)
    phone_condition = db.Column(db.String(20))
    age = db.Column(db.Integer)
    
    # Customer information fields
    customer_name = db.Column(db.String(100))  # اسم العميل
    customer_id = db.Column(db.String(50))     # رقم الهوية / الإقامة
    phone_color = db.Column(db.String(50))     # لون الجوال
    phone_memory = db.Column(db.String(50))    # الذاكرة
    buyer_name = db.Column(db.String(100))     # اسم المشتري

class PhoneType(db.Model):
    """نموذج أنواع الهواتف - للتحكم في العلامات التجارية والموديلات"""
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), default='smartphone')  # smartphone, tablet, etc.
    release_year = db.Column(db.Integer)
    is_active = db.Column(db.Boolean, default=True)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

# Transaction model removed - replaced by Sale and SaleItem models

class Transaction(db.Model):
    """نموذج المعاملات - للاحتفاظ بسجل المعاملات"""
    id = db.Column(db.Integer, primary_key=True)
    phone_id = db.Column(db.Integer, db.ForeignKey('phone.id'), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  # buy, sell
    serial_number = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)  # السعر قبل الضريبة
    price_with_vat = db.Column(db.Float, nullable=False)  # السعر مع الضريبة
    vat_amount = db.Column(db.Float, nullable=False)  # مبلغ الضريبة
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    notes = db.Column(db.Text)

class Sale(db.Model):
    """نموذج عملية البيع - يمكن أن تحتوي على عدة منتجات"""
    id = db.Column(db.Integer, primary_key=True)
    sale_number = db.Column(db.String(50), unique=True, nullable=False)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Company Information (معلومات الشركة)
    company_name = db.Column(db.String(200), nullable=False, default="شركة الهواتف الذكية")
    company_vat_number = db.Column(db.String(50), nullable=False, default="123456789012345")
    company_address = db.Column(db.Text, nullable=False, default="الرياض، المملكة العربية السعودية")
    company_phone = db.Column(db.String(20), nullable=False, default="+966-11-123-4567")
    
    # Customer Information (معلومات العميل)
    customer_name = db.Column(db.String(100), nullable=False)
    customer_phone = db.Column(db.String(20))
    customer_email = db.Column(db.String(100))
    customer_address = db.Column(db.Text)
    
    # Sale Details (تفاصيل البيع)
    subtotal = db.Column(db.Float, nullable=False, default=0.0)  # المبلغ قبل الضريبة
    vat_amount = db.Column(db.Float, nullable=False, default=0.0)  # مبلغ الضريبة
    total_amount = db.Column(db.Float, nullable=False, default=0.0)  # المبلغ الإجمالي
    payment_method = db.Column(db.String(50), default="نقدي")
    
    # Additional Fields
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default="مكتمل")  # مكتمل، ملغي، مرفوض
    
    # Relationships
    items = db.relationship('SaleItem', backref='sale', lazy=True, cascade='all, delete-orphan')

class AccessoryCategory(db.Model):
    """نموذج فئات الأكسسوارات - للتحكم في الفئات"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    arabic_name = db.Column(db.String(100), nullable=False)  # الاسم بالعربية
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

class Accessory(db.Model):
    """نموذج الأكسسوارات والمستلزمات"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), nullable=False)  # accessory, charger, case, screen_protector
    description = db.Column(db.Text)
    purchase_price = db.Column(db.Float, nullable=False)  # سعر الشراء (بدون ضريبة)
    selling_price = db.Column(db.Float, nullable=False)   # سعر البيع (بدون ضريبة)
    purchase_price_with_vat = db.Column(db.Float, nullable=False)  # سعر الشراء (مع ضريبة)
    selling_price_with_vat = db.Column(db.Float, nullable=False)   # سعر البيع (مع ضريبة)
    quantity_in_stock = db.Column(db.Integer, nullable=False, default=0)
    min_quantity = db.Column(db.Integer, default=5)  # الحد الأدنى للمخزون
    supplier = db.Column(db.String(200))
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

class SaleItem(db.Model):
    """نموذج عنصر البيع - كل منتج في عملية البيع"""
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sale.id'), nullable=False)
    
    # Product Information (معلومات المنتج)
    product_type = db.Column(db.String(50), nullable=False)  # phone, accessory, charger, etc.
    product_name = db.Column(db.String(200), nullable=False)
    product_description = db.Column(db.Text)
    serial_number = db.Column(db.String(100))  # للهواتف فقط
    
    # Pricing (التسعير)
    unit_price = db.Column(db.Float, nullable=False)  # سعر الوحدة قبل الضريبة
    quantity = db.Column(db.Integer, nullable=False, default=1)
    total_price = db.Column(db.Float, nullable=False)  # السعر الإجمالي للكمية
    
    # Additional Fields
    notes = db.Column(db.Text)

# Invoice model removed - invoices are now generated from Sale data



@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Create admin user if not exists
def create_admin_user():
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(username='admin', password=generate_password_hash('admin123'), is_admin=True)
        db.session.add(admin)
        db.session.commit()
        print("Admin user created successfully!")

def create_default_phone_types():
    """Create default phone types if they don't exist"""
    default_types = [
        # Apple - Most Popular Models
        {'brand': 'Apple', 'model': 'iPhone 15 Pro Max', 'category': 'flagship', 'release_year': 2024},
        {'brand': 'Apple', 'model': 'iPhone 15 Pro', 'category': 'flagship', 'release_year': 2024},
        {'brand': 'Apple', 'model': 'iPhone 15 Plus', 'category': 'flagship', 'release_year': 2024},
        {'brand': 'Apple', 'model': 'iPhone 15', 'category': 'flagship', 'release_year': 2024},
        {'brand': 'Apple', 'model': 'iPhone 14 Pro Max', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Apple', 'model': 'iPhone 14 Pro', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Apple', 'model': 'iPhone 14 Plus', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Apple', 'model': 'iPhone 14', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Apple', 'model': 'iPhone 13 Pro Max', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Apple', 'model': 'iPhone 13 Pro', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Apple', 'model': 'iPhone 13', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Apple', 'model': 'iPhone 12 Pro Max', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'Apple', 'model': 'iPhone 12 Pro', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'Apple', 'model': 'iPhone 12', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'Apple', 'model': 'iPhone 11 Pro Max', 'category': 'flagship', 'release_year': 2020},
        {'brand': 'Apple', 'model': 'iPhone 11 Pro', 'category': 'flagship', 'release_year': 2020},
        {'brand': 'Apple', 'model': 'iPhone 11', 'category': 'flagship', 'release_year': 2020},
        {'brand': 'Apple', 'model': 'iPhone XS Max', 'category': 'flagship', 'release_year': 2019},
        {'brand': 'Apple', 'model': 'iPhone XS', 'category': 'flagship', 'release_year': 2019},
        {'brand': 'Apple', 'model': 'iPhone XR', 'category': 'flagship', 'release_year': 2019},
        {'brand': 'Apple', 'model': 'iPhone X', 'category': 'flagship', 'release_year': 2018},
        {'brand': 'Apple', 'model': 'iPhone 8 Plus', 'category': 'flagship', 'release_year': 2018},
        {'brand': 'Apple', 'model': 'iPhone 8', 'category': 'flagship', 'release_year': 2018},
        
        # Samsung - Most Popular Models
        {'brand': 'Samsung', 'model': 'Galaxy S24 Ultra', 'category': 'flagship', 'release_year': 2024},
        {'brand': 'Samsung', 'model': 'Galaxy S24+', 'category': 'flagship', 'release_year': 2024},
        {'brand': 'Samsung', 'model': 'Galaxy S24', 'category': 'flagship', 'release_year': 2024},
        {'brand': 'Samsung', 'model': 'Galaxy S23 Ultra', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Samsung', 'model': 'Galaxy S23+', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Samsung', 'model': 'Galaxy S23', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Samsung', 'model': 'Galaxy S22 Ultra', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Samsung', 'model': 'Galaxy S22+', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Samsung', 'model': 'Galaxy S22', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Samsung', 'model': 'Galaxy S21 Ultra', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'Samsung', 'model': 'Galaxy S21+', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'Samsung', 'model': 'Galaxy S21', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'Samsung', 'model': 'Galaxy S20 Ultra', 'category': 'flagship', 'release_year': 2020},
        {'brand': 'Samsung', 'model': 'Galaxy S20+', 'category': 'flagship', 'release_year': 2020},
        {'brand': 'Samsung', 'model': 'Galaxy S20', 'category': 'flagship', 'release_year': 2020},
        {'brand': 'Samsung', 'model': 'Galaxy Note 20 Ultra', 'category': 'flagship', 'release_year': 2020},
        {'brand': 'Samsung', 'model': 'Galaxy Note 20', 'category': 'flagship', 'release_year': 2020},
        {'brand': 'Samsung', 'model': 'Galaxy Note 10+', 'category': 'flagship', 'release_year': 2019},
        {'brand': 'Samsung', 'model': 'Galaxy Note 10', 'category': 'flagship', 'release_year': 2019},
        {'brand': 'Samsung', 'model': 'Galaxy A54', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Samsung', 'model': 'Galaxy A34', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Samsung', 'model': 'Galaxy A24', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Samsung', 'model': 'Galaxy A14', 'category': 'midrange', 'release_year': 2023},
        
        # Huawei - Popular Models
        {'brand': 'Huawei', 'model': 'P60 Pro', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Huawei', 'model': 'P60', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Huawei', 'model': 'P50 Pro', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Huawei', 'model': 'P50', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Huawei', 'model': 'P40 Pro+', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'Huawei', 'model': 'P40 Pro', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'Huawei', 'model': 'P40', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'Huawei', 'model': 'Mate 60 Pro', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Huawei', 'model': 'Mate 50 Pro', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Huawei', 'model': 'Mate 40 Pro', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'Huawei', 'model': 'Nova 11', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Huawei', 'model': 'Nova 10', 'category': 'midrange', 'release_year': 2022},
        
        # Xiaomi - Popular Models
        {'brand': 'Xiaomi', 'model': '14 Ultra', 'category': 'flagship', 'release_year': 2024},
        {'brand': 'Xiaomi', 'model': '14 Pro', 'category': 'flagship', 'release_year': 2024},
        {'brand': 'Xiaomi', 'model': '14', 'category': 'flagship', 'release_year': 2024},
        {'brand': 'Xiaomi', 'model': '13 Ultra', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Xiaomi', 'model': '13 Pro', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Xiaomi', 'model': '13', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Xiaomi', 'model': '13T Pro', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Xiaomi', 'model': '13T', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Xiaomi', 'model': '12S Ultra', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Xiaomi', 'model': '12 Pro', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Xiaomi', 'model': '12', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Xiaomi', 'model': 'Redmi Note 13 Pro+', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Xiaomi', 'model': 'Redmi Note 13 Pro', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Xiaomi', 'model': 'Redmi Note 13', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Xiaomi', 'model': 'Redmi Note 12 Pro+', 'category': 'midrange', 'release_year': 2022},
        {'brand': 'Xiaomi', 'model': 'Redmi Note 12 Pro', 'category': 'midrange', 'release_year': 2022},
        {'brand': 'Xiaomi', 'model': 'Redmi Note 12', 'category': 'midrange', 'release_year': 2022},
        
        # OnePlus - Popular Models
        {'brand': 'OnePlus', 'model': '12', 'category': 'flagship', 'release_year': 2024},
        {'brand': 'OnePlus', 'model': '11', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'OnePlus', 'model': '10 Pro', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'OnePlus', 'model': '10', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'OnePlus', 'model': '9 Pro', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'OnePlus', 'model': '9', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'OnePlus', 'model': '8 Pro', 'category': 'flagship', 'release_year': 2020},
        {'brand': 'OnePlus', 'model': '8', 'category': 'flagship', 'release_year': 2020},
        {'brand': 'OnePlus', 'model': 'Nord 3', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'OnePlus', 'model': 'Nord 2T', 'category': 'midrange', 'release_year': 2022},
        {'brand': 'OnePlus', 'model': 'Nord 2', 'category': 'midrange', 'release_year': 2021},
        
        # Google - Popular Models
        {'brand': 'Google', 'model': 'Pixel 8 Pro', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Google', 'model': 'Pixel 8', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Google', 'model': 'Pixel 7 Pro', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Google', 'model': 'Pixel 7', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Google', 'model': 'Pixel 6 Pro', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'Google', 'model': 'Pixel 6', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'Google', 'model': 'Pixel 5', 'category': 'flagship', 'release_year': 2020},
        {'brand': 'Google', 'model': 'Pixel 4 XL', 'category': 'flagship', 'release_year': 2019},
        {'brand': 'Google', 'model': 'Pixel 4', 'category': 'flagship', 'release_year': 2019},
        {'brand': 'Google', 'model': 'Pixel 3 XL', 'category': 'flagship', 'release_year': 2018},
        {'brand': 'Google', 'model': 'Pixel 3', 'category': 'flagship', 'release_year': 2018},
        
        # Oppo - Popular Models
        {'brand': 'Oppo', 'model': 'Find X7 Ultra', 'category': 'flagship', 'release_year': 2024},
        {'brand': 'Oppo', 'model': 'Find X6 Pro', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Oppo', 'model': 'Find X6', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Oppo', 'model': 'Find X5 Pro', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Oppo', 'model': 'Find X5', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Oppo', 'model': 'Find X3 Pro', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'Oppo', 'model': 'Find X3', 'category': 'flagship', 'release_year': 2021},
        {'brand': 'Oppo', 'model': 'Reno 11 Pro', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Oppo', 'model': 'Reno 11', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Oppo', 'model': 'Reno 10 Pro+', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Oppo', 'model': 'Reno 10 Pro', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Oppo', 'model': 'Reno 10', 'category': 'midrange', 'release_year': 2023},
        
        # Vivo - Popular Models
        {'brand': 'Vivo', 'model': 'X100 Pro', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Vivo', 'model': 'X100', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Vivo', 'model': 'X90 Pro+', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Vivo', 'model': 'X90 Pro', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Vivo', 'model': 'X90', 'category': 'flagship', 'release_year': 2022},
        {'brand': 'Vivo', 'model': 'V29 Pro', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Vivo', 'model': 'V29', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Vivo', 'model': 'V27 Pro', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Vivo', 'model': 'V27', 'category': 'midrange', 'release_year': 2023},
        
        # Realme - Popular Models
        {'brand': 'Realme', 'model': 'GT 5 Pro', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Realme', 'model': 'GT 5', 'category': 'flagship', 'release_year': 2023},
        {'brand': 'Realme', 'model': 'GT Neo 5', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Realme', 'model': 'GT Neo 4', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Realme', 'model': 'GT Neo 3', 'category': 'midrange', 'release_year': 2022},
        {'brand': 'Realme', 'model': 'Number Series', 'category': 'midrange', 'release_year': 2023},
        {'brand': 'Realme', 'model': 'C Series', 'category': 'budget', 'release_year': 2023},
    ]
    
    for phone_data in default_types:
        existing = PhoneType.query.filter_by(brand=phone_data['brand'], model=phone_data['model']).first()
        if not existing:
            phone_type = PhoneType(**phone_data)
            db.session.add(phone_type)
    
    try:
        db.session.commit()
        print("Default phone types created successfully!")
    except Exception as e:
        db.session.rollback()
        print(f"Error creating default phone types: {e}")

def create_default_accessory_categories():
    """Create default accessory categories if they don't exist"""
    default_categories = [
        {'name': 'accessory', 'arabic_name': 'إكسسوار', 'description': 'إكسسوارات عامة'},
        {'name': 'charger', 'arabic_name': 'شاحن', 'description': 'شواحن الهواتف'},
        {'name': 'case', 'arabic_name': 'غلاف', 'description': 'أغلفة الهواتف'},
        {'name': 'screen_protector', 'arabic_name': 'حماية الشاشة', 'description': 'حماية شاشة الهاتف'},
        {'name': 'cable', 'arabic_name': 'كابل', 'description': 'كابلات البيانات والشحن'},
        {'name': 'headphone', 'arabic_name': 'سماعات', 'description': 'سماعات الهواتف'},
        {'name': 'other', 'arabic_name': 'أخرى', 'description': 'فئات أخرى'},
    ]
    
    for category_data in default_categories:
        existing = AccessoryCategory.query.filter_by(name=category_data['name']).first()
        if not existing:
            category = AccessoryCategory(**category_data)
            db.session.add(category)
    
    try:
        db.session.commit()
        print("Default accessory categories created successfully!")
    except Exception as e:
        db.session.rollback()
        print(f"Error creating default accessory categories: {e}")

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    static_favicon = os.path.join(app.root_path, 'static', 'favicon.ico')
    if os.path.exists(static_favicon):
        return send_file(static_favicon)
    return ("", 204)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user:
            # Backward-compatible check: if stored value looks hashed, verify hash; otherwise compare plaintext
            is_hashed = user.password.startswith('pbkdf2:') or user.password.startswith('scrypt:') or user.password.startswith('argon2:')
            if (is_hashed and check_password_hash(user.password, password)) or (not is_hashed and user.password == password):
                # If old plaintext password, upgrade it to hashed transparently
                if not is_hashed:
                    user.password = generate_password_hash(password)
                    db.session.commit()
                login_user(user)
                return redirect(url_for('dashboard'))
        flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'error')
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    phones = Phone.query.all()
    
    # Calculate financial summaries for current inventory
    total_phones = len(phones)
    total_purchase_value = sum(phone.purchase_price for phone in phones)
    total_selling_value = sum(phone.selling_price for phone in phones)
    total_expected_profit = total_selling_value - total_purchase_value
    
    # Recent sales
    recent_sales = Sale.query.order_by(Sale.date_created.desc()).limit(10).all()
    
    # Sales statistics
    total_sales = Sale.query.count()
    total_sales_amount = sum(sale.total_amount for sale in Sale.query.all())
    
    # Calculate sales subtotal and VAT
    total_sales_subtotal = sum(sale.subtotal for sale in Sale.query.all())
    total_vat_amount = sum(sale.vat_amount for sale in Sale.query.all())
    # Calculate actual profit as the difference between selling and purchase prices
    total_actual_profit = 0.0  # We'll calculate this differently if needed
    
    return render_template('dashboard.html', 
                         phones=phones,
                         total_phones=total_phones,
                         total_purchase_value=total_purchase_value,
                         total_selling_value=total_selling_value,
                         total_expected_profit=total_expected_profit,
                         total_sales_count=total_sales,
                         total_sales_amount=total_sales_amount,
                         total_sales_subtotal=total_sales_subtotal,
                         total_vat_amount=total_vat_amount,
                         total_actual_profit=total_actual_profit,
                         recent_sales=recent_sales)

# Transactions route removed - replaced by sales system

def generate_barcode(phone_number):
    # Create barcode with phone number only
    barcode_class = barcode.get_barcode_class('code128')
    barcode_instance = barcode_class(phone_number, writer=ImageWriter())
    
    # Set custom options for the barcode
    options = {
        'module_width': 0.2,  # Width of each bar
        'module_height': 15,  # Height of the barcode
        'font_size': 10,      # Font size for the number
        'text_distance': 2,   # Distance between barcode and text
        'quiet_zone': 2,      # Quiet zone around the barcode
        'dpi': 300           # DPI for better quality
    }
    
    # Create barcodes directory if it doesn't exist
    if not os.path.exists('static/barcodes'):
        os.makedirs('static/barcodes')
    
    # Save barcode image with custom options
    filename = f"static/barcodes/{phone_number}"
    barcode_path = barcode_instance.save(filename, options)
    
    # Convert the saved image to the exact size (4.4cm x 2.5cm)
    img = Image.open(barcode_path)
    # Convert cm to pixels (1cm = 37.795276 pixels at 96 DPI)
    width_px = int(4.4 * 37.795276)
    height_px = int(2.5 * 37.795276)
    img = img.resize((width_px, height_px), Image.Resampling.LANCZOS)
    img.save(barcode_path)
    
    return barcode_path

@app.route('/barcode/<phone_number>')
@login_required
def get_barcode(phone_number):
    phone = Phone.query.filter_by(phone_number=phone_number).first()
    if phone and phone.barcode_path:
        return send_file(phone.barcode_path, mimetype='image/png')
    return "Barcode not found", 404

def generate_unique_phone_number():
    # Get the highest existing phone number
    highest_phone = db.session.query(func.max(Phone.phone_number)).scalar()
    
    if highest_phone is None:
        # If no phones exist, start from 1
        next_number = 1
    else:
        # Convert the highest phone number to integer and increment
        next_number = int(highest_phone) + 1
    
    # Check if we've reached the limit
    if next_number > 100000:
        raise ValueError("Maximum number of phones (100000) reached")
    
    # Format the number with leading zeros to make it 6 digits
    phone_number = f"{next_number:06d}"
    return phone_number

def process_barcode_input(barcode_input):
    """Process barcode input and return phone number or None if invalid"""
    if not barcode_input:
        return None
    
    # Clean the barcode input (remove spaces, dashes, etc.)
    cleaned_barcode = ''.join(filter(str.isdigit, barcode_input))
    
    # Check if it's a valid 6-digit number (our internal format)
    if len(cleaned_barcode) == 6 and cleaned_barcode.isdigit():
        return cleaned_barcode
    
    # If it's a different format, we can add validation here
    # For now, return the cleaned input if it's numeric
    if cleaned_barcode.isdigit():
        return cleaned_barcode
    
    return None

@app.route('/scan_barcode', methods=['GET', 'POST'])
@login_required
def scan_barcode():
    if request.method == 'POST':
        barcode_input = request.form.get('barcode_input')
        phone_type = request.form.get('phone_type', 'new')  # new or used
        
        if not barcode_input:
            flash('يرجى إدخال الباركود', 'error')
            return redirect(url_for('scan_barcode'))
        
        phone_number = process_barcode_input(barcode_input)
        if not phone_number:
            flash('باركود غير صحيح', 'error')
            return redirect(url_for('scan_barcode'))
        
        # Check if phone number already exists
        existing_phone = Phone.query.filter_by(phone_number=phone_number).first()
        if existing_phone:
            flash(f'الهاتف برقم {phone_number} موجود بالفعل في النظام', 'error')
            return redirect(url_for('scan_barcode'))
        
        # Redirect to appropriate add phone form with pre-filled barcode
        if phone_type == 'used':
            return redirect(url_for('add_used_phone', barcode=phone_number))
        else:
            return redirect(url_for('add_new_phone', barcode=phone_number))
    
    return render_template('scan_barcode.html')

@app.route('/print_barcode/<phone_number>')
@login_required
def print_barcode(phone_number):
    phone = Phone.query.filter_by(phone_number=phone_number).first()
    if phone and phone.barcode_path:
        return render_template('print_barcode.html', phone=phone)
    flash('لم يتم العثور على الباركود', 'error')
    return redirect(url_for('dashboard'))

@app.route('/add_new_phone', methods=['GET', 'POST'])
@login_required
def add_new_phone():
    if request.method == 'POST':
        try:
            brand = request.form.get('brand')
            model = request.form.get('model')
            purchase_price = float(request.form.get('purchase_price'))  # Price without VAT
            selling_price = float(request.form.get('selling_price'))    # Price without VAT
            serial_number = request.form.get('serial_number')
            warranty = int(request.form.get('warranty'))
            
            # Calculate VAT amounts
            purchase_vat = calculate_vat(purchase_price)
            selling_vat = calculate_vat(selling_price)
            
            # Calculate prices with VAT
            purchase_price_with_vat = calculate_price_with_vat(purchase_price)
            selling_price_with_vat = calculate_price_with_vat(selling_price)
            description = request.form.get('description')
            barcode_input = request.form.get('barcode_input')
            
            # Customer information fields
            customer_name = request.form.get('customer_name')
            customer_id = request.form.get('customer_id')
            phone_color = request.form.get('phone_color')
            phone_memory = request.form.get('phone_memory')
            buyer_name = request.form.get('buyer_name')
            
            # Check if serial number already exists
            existing_phone = Phone.query.filter_by(serial_number=serial_number).first()
            if existing_phone:
                flash('الرقم التسلسلي موجود بالفعل في النظام', 'error')
                return redirect(url_for('add_new_phone'))
            
            # Process barcode input
            if barcode_input:
                phone_number = process_barcode_input(barcode_input)
                if not phone_number:
                    flash('باركود غير صحيح', 'error')
                    return redirect(url_for('add_new_phone'))
                existing_phone = Phone.query.filter_by(phone_number=phone_number).first()
                if existing_phone:
                    flash(f'الهاتف برقم {phone_number} موجود بالفعل في النظام', 'error')
                    return redirect(url_for('add_new_phone'))
            else:
                try:
                    phone_number = generate_unique_phone_number()
                except ValueError as e:
                    flash(str(e), 'error')
                    return redirect(url_for('add_new_phone'))
            
            # Generate barcode automatically
            barcode_path = generate_barcode(phone_number)
            
            new_phone = Phone(
                brand=brand,
                model=model,
                condition='new',
                purchase_price=purchase_price,
                selling_price=selling_price,
                purchase_price_with_vat=purchase_price_with_vat,
                selling_price_with_vat=selling_price_with_vat,
                serial_number=serial_number,
                phone_number=phone_number,
                barcode_path=barcode_path,
                description=description,
                warranty=warranty,
                customer_name=customer_name,
                customer_id=customer_id,
                phone_color=phone_color,
                phone_memory=phone_memory,
                buyer_name=buyer_name
            )
            
            db.session.add(new_phone)
            db.session.commit()
            
            # Record a buy transaction
            buy_tx = Transaction(
                phone_id=new_phone.id,
                transaction_type='buy',
                serial_number=serial_number,
                price=purchase_price,
                price_with_vat=purchase_price_with_vat,
                vat_amount=purchase_vat,
                user_id=current_user.id,
                customer_name=customer_name,
                customer_phone=None,
                notes='شراء هاتف جديد'
            )
            db.session.add(buy_tx)
            db.session.commit()
            
            flash('تمت إضافة الهاتف الجديد بنجاح', 'success')
            return redirect(url_for('dashboard'))
        except ValueError:
            db.session.rollback()
            flash('خطأ في إدخال البيانات. يرجى التحقق من القيم المدخلة', 'error')
            return redirect(url_for('add_new_phone'))
        except Exception as e:
            db.session.rollback()
            flash(f'حدث خطأ: {str(e)}', 'error')
            return redirect(url_for('add_new_phone'))
    
    # Pre-fill barcode if provided in URL parameter
    barcode = request.args.get('barcode', '')
    
    # Get brands and models data for the dropdown
    brands = {}
    phone_types = PhoneType.query.all()
    for phone_type in phone_types:
        if phone_type.brand not in brands:
            brands[phone_type.brand] = []
        brands[phone_type.brand].append(phone_type.model)
    
    return render_template('add_new_phone.html', barcode=barcode, brands=brands)

@app.route('/add_used_phone', methods=['GET', 'POST'])
@login_required
def add_used_phone():
    if request.method == 'POST':
        try:
            brand = request.form.get('brand')
            model = request.form.get('model')
            purchase_price = float(request.form.get('purchase_price'))  # Price without VAT
            selling_price = float(request.form.get('selling_price'))    # Price without VAT
            serial_number = request.form.get('serial_number')
            phone_condition = request.form.get('phone_condition')
            age = int(request.form.get('age'))
            
            # Calculate VAT amounts
            purchase_vat = calculate_vat(purchase_price)
            selling_vat = calculate_vat(selling_price)
            
            # Calculate prices with VAT
            purchase_price_with_vat = calculate_price_with_vat(purchase_price)
            selling_price_with_vat = calculate_price_with_vat(selling_price)
            description = request.form.get('description')
            barcode_input = request.form.get('barcode_input')
            
            # Customer information fields
            customer_name = request.form.get('customer_name')
            customer_id = request.form.get('customer_id')
            phone_color = request.form.get('phone_color')
            phone_memory = request.form.get('phone_memory')
            buyer_name = request.form.get('buyer_name')
            
            existing_phone = Phone.query.filter_by(serial_number=serial_number).first()
            if existing_phone:
                flash('الرقم التسلسلي موجود بالفعل في النظام', 'error')
                return redirect(url_for('add_used_phone'))
            
            # Process barcode input
            if barcode_input:
                phone_number = process_barcode_input(barcode_input)
                if not phone_number:
                    flash('باركود غير صحيح', 'error')
                    return redirect(url_for('add_used_phone'))
                existing_phone = Phone.query.filter_by(phone_number=phone_number).first()
                if existing_phone:
                    flash(f'الهاتف برقم {phone_number} موجود بالفعل في النظام', 'error')
                    return redirect(url_for('add_used_phone'))
            else:
                try:
                    phone_number = generate_unique_phone_number()
                except ValueError as e:
                    flash(str(e), 'error')
                    return redirect(url_for('add_used_phone'))
            
            barcode_path = generate_barcode(phone_number)
            
            used_phone = Phone(
                brand=brand,
                model=model,
                condition='used',
                purchase_price=purchase_price,
                selling_price=selling_price,
                purchase_price_with_vat=purchase_price_with_vat,
                selling_price_with_vat=selling_price_with_vat,
                serial_number=serial_number,
                phone_number=phone_number,
                barcode_path=barcode_path,
                phone_condition=phone_condition,
                age=age,
                description=description,
                customer_name=customer_name,
                customer_id=customer_id,
                phone_color=phone_color,
                phone_memory=phone_memory,
                buyer_name=buyer_name
            )
            db.session.add(used_phone)
            db.session.commit()
            
            # Record a buy transaction
            buy_tx = Transaction(
                phone_id=used_phone.id,
                transaction_type='buy',
                serial_number=serial_number,
                price=purchase_price,
                price_with_vat=purchase_price_with_vat,
                vat_amount=purchase_vat,
                user_id=current_user.id,
                customer_name=customer_name,
                customer_phone=None,
                notes='شراء هاتف مستعمل'
            )
            db.session.add(buy_tx)
            db.session.commit()
            
            flash('تمت إضافة الهاتف المستعمل بنجاح', 'success')
            return redirect(url_for('dashboard'))
        except ValueError:
            db.session.rollback()
            flash('خطأ في إدخال البيانات. يرجى التحقق من القيم المدخلة', 'error')
            return redirect(url_for('add_used_phone'))
        except Exception as e:
            db.session.rollback()
            flash(f'حدث خطأ: {str(e)}', 'error')
            return redirect(url_for('add_used_phone'))
    
    # Pre-fill barcode if provided in URL parameter
    barcode = request.args.get('barcode', '')
    
    # Get brands and models data for the dropdown
    brands = {}
    phone_types = PhoneType.query.all()
    for phone_type in phone_types:
        if phone_type.brand not in brands:
            brands[phone_type.brand] = []
        brands[phone_type.brand].append(phone_type.model)
    
    return render_template('add_used_phone.html', barcode=barcode, brands=brands)

@app.route('/dashboard/delete/<int:phone_id>', methods=['POST'])
@login_required
def delete_phone(phone_id):
    phone = Phone.query.get_or_404(phone_id)
    try:
        db.session.delete(phone)
        db.session.commit()
        flash('تم حذف الهاتف بنجاح', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'حدث خطأ أثناء حذف الهاتف: {str(e)}', 'error')
    return redirect(url_for('dashboard'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# Invoice routes removed - invoices are now generated from Sale data

@app.route('/create_sale')
@login_required
def create_sale_page():
    """Show create sale page"""
    phones = Phone.query.all()
    accessories = Accessory.query.all()
    
    # Convert Phone objects to dictionaries for JSON serialization
    phones_data = []
    for phone in phones:
        phones_data.append({
            'id': phone.id,
            'brand': phone.brand,
            'model': phone.model,
            'serial_number': phone.serial_number,
            'selling_price': phone.selling_price,
            'description': phone.description or ''
        })
    
    # Convert Accessory objects to dictionaries
    accessories_data = []
    for accessory in accessories:
        accessories_data.append({
            'id': accessory.id,
            'name': accessory.name,
            'category': accessory.category,
            'description': accessory.description or '',
            'selling_price': accessory.selling_price,
            'quantity_in_stock': accessory.quantity_in_stock
        })
    
    return render_template('create_sale.html', phones=phones_data, accessories=accessories_data)

@app.route('/create_sale', methods=['POST'])
@login_required
def create_sale():
    """Create a new sale with multiple items"""
    try:
        data = request.get_json()
        
        # Create sale record
        sale = Sale(
            sale_number=generate_invoice_number(),
            customer_name=data['customer_name'],
            customer_phone=data['customer_phone'],
            customer_email=data['customer_email'],
            customer_address=data['customer_address'],
            payment_method=data['payment_method'],
            notes=data['notes']
        )
        
        # Calculate totals
        subtotal = sum(item['totalPrice'] for item in data['items'])
        vat_amount = subtotal * 0.15
        total_amount = subtotal + vat_amount
        
        sale.subtotal = subtotal
        sale.vat_amount = vat_amount
        sale.total_amount = total_amount
        
        db.session.add(sale)
        db.session.flush()  # Get the sale ID
        
        # Add sale items
        for item_data in data['items']:
            sale_item = SaleItem(
                sale_id=sale.id,
                product_type=item_data['type'],
                product_name=item_data['name'],
                product_description=item_data['description'],
                unit_price=item_data['unitPrice'],
                quantity=item_data['quantity'],
                total_price=item_data['totalPrice']
            )
            
            # Add serial number for phones
            if item_data['type'] == 'phone':
                phone = Phone.query.get(item_data['id'])
                if phone:
                    sale_item.serial_number = phone.serial_number
                    # Remove phone from inventory
                    db.session.delete(phone)
            elif item_data['type'] in ['accessory', 'charger', 'case', 'screen_protector']:
                # Update accessory stock
                accessory = Accessory.query.get(item_data['id'])
                if accessory:
                    accessory.quantity_in_stock -= item_data['quantity']
                    if accessory.quantity_in_stock < 0:
                        accessory.quantity_in_stock = 0
            
            db.session.add(sale_item)
        
        db.session.commit()
        
        return jsonify({'success': True, 'sale_id': sale.id})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/sale/<int:sale_id>')
@login_required
def view_sale(sale_id):
    """View sale details"""
    sale = Sale.query.get_or_404(sale_id)
    return render_template('view_sale.html', sale=sale)

@app.route('/accessories')
@login_required
def list_accessories():
    """List all accessories"""
    accessories = Accessory.query.order_by(Accessory.date_added.desc()).all()
    
    # Calculate totals considering quantity
    total_purchase_value = sum(acc.purchase_price_with_vat * acc.quantity_in_stock for acc in accessories)
    total_selling_value = sum(acc.selling_price_with_vat * acc.quantity_in_stock for acc in accessories)
    total_quantity = sum(acc.quantity_in_stock for acc in accessories)
    
    # Get categories for display
    categories = AccessoryCategory.query.all()
    category_map = {cat.name: cat.arabic_name for cat in categories}
    
    return render_template('list_accessories.html', 
                         accessories=accessories,
                         total_purchase_value=total_purchase_value,
                         total_selling_value=total_selling_value,
                         total_quantity=total_quantity,
                         category_map=category_map)

@app.route('/add_accessory', methods=['GET', 'POST'])
@login_required
def add_accessory():
    """Add new accessory"""
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            category = request.form.get('category')
            description = request.form.get('description')
            purchase_price = float(request.form.get('purchase_price'))
            selling_price = float(request.form.get('selling_price'))
            quantity = int(request.form.get('quantity', 0))
            supplier = request.form.get('supplier')
            notes = request.form.get('notes')
            
            # Calculate VAT amounts
            purchase_vat = calculate_vat(purchase_price)
            selling_vat = calculate_vat(selling_price)
            
            # Calculate prices with VAT
            purchase_price_with_vat = calculate_price_with_vat(purchase_price)
            selling_price_with_vat = calculate_price_with_vat(selling_price)
            
            accessory = Accessory(
                name=name,
                category=category,
                description=description,
                purchase_price=purchase_price,
                selling_price=selling_price,
                purchase_price_with_vat=purchase_price_with_vat,
                selling_price_with_vat=selling_price_with_vat,
                quantity_in_stock=quantity,
                supplier=supplier,
                notes=notes
            )
            
            db.session.add(accessory)
            db.session.commit()
            
            flash('تمت إضافة الأكسسوار بنجاح', 'success')
            return redirect(url_for('list_accessories'))
            
        except ValueError:
            flash('خطأ في إدخال البيانات. يرجى التحقق من القيم المدخلة', 'error')
            return redirect(url_for('add_accessory'))
        except Exception as e:
            db.session.rollback()
            flash(f'حدث خطأ: {str(e)}', 'error')
            return redirect(url_for('add_accessory'))
    
    # Get categories for the dropdown
    categories = AccessoryCategory.query.all()
    return render_template('add_accessory.html', categories=categories)

@app.route('/edit_accessory/<int:accessory_id>', methods=['GET', 'POST'])
@login_required
def edit_accessory(accessory_id):
    """Edit existing accessory"""
    accessory = Accessory.query.get_or_404(accessory_id)
    
    if request.method == 'POST':
        try:
            accessory.name = request.form.get('name')
            accessory.category = request.form.get('category')
            accessory.description = request.form.get('description')
            accessory.purchase_price = float(request.form.get('purchase_price'))
            accessory.selling_price = float(request.form.get('selling_price'))
            accessory.quantity_in_stock = int(request.form.get('quantity', 0))
            accessory.supplier = request.form.get('supplier')
            accessory.notes = request.form.get('notes')
            
            # Recalculate VAT amounts
            purchase_vat = calculate_vat(accessory.purchase_price)
            selling_vat = calculate_vat(accessory.selling_price)
            
            # Recalculate prices with VAT
            accessory.purchase_price_with_vat = calculate_price_with_vat(accessory.purchase_price)
            accessory.selling_price_with_vat = calculate_price_with_vat(accessory.selling_price)
            
            db.session.commit()
            
            flash('تم تحديث الأكسسوار بنجاح', 'success')
            return redirect(url_for('list_accessories'))
            
        except ValueError:
            flash('خطأ في إدخال البيانات. يرجى التحقق من القيم المدخلة', 'error')
        except Exception as e:
            db.session.rollback()
            flash(f'حدث خطأ: {str(e)}', 'error')
    
    # Get categories for the dropdown
    categories = AccessoryCategory.query.all()
    return render_template('edit_accessory.html', accessory=accessory, categories=categories)

@app.route('/delete_accessory/<int:accessory_id>', methods=['DELETE'])
@login_required
def delete_accessory(accessory_id):
    """Delete accessory"""
    try:
        accessory = Accessory.query.get_or_404(accessory_id)
        db.session.delete(accessory)
        db.session.commit()
        return jsonify({'success': True, 'message': 'تم حذف الأكسسوار بنجاح'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/search')
@login_required
def search():
    """Search for phones and accessories"""
    search_term = request.args.get('search_term', '').strip()
    search_type = request.args.get('search_type', 'all')
    condition = request.args.get('condition', '')
    
    phones = []
    accessories = []
    
    if search_term:
        # Search in phones
        if search_type in ['all', 'phones']:
            phone_query = Phone.query
            
            # Add condition filter if specified
            if condition:
                phone_query = phone_query.filter_by(condition=condition)
            
            # Search in multiple phone fields
            phone_query = phone_query.filter(
                db.or_(
                    Phone.phone_number.contains(search_term),
                    Phone.serial_number.contains(search_term),
                    Phone.brand.contains(search_term),
                    Phone.model.contains(search_term),
                    Phone.phone_color.contains(search_term),
                    Phone.phone_memory.contains(search_term),
                    Phone.description.contains(search_term),
                    Phone.customer_name.contains(search_term),
                    Phone.customer_id.contains(search_term)
                )
            )
            
            phones = phone_query.all()
        
        # Search in accessories
        if search_type in ['all', 'accessories']:
            accessory_query = Accessory.query.filter(
                db.or_(
                    Accessory.name.contains(search_term),
                    Accessory.category.contains(search_term),
                    Accessory.description.contains(search_term),
                    Accessory.supplier.contains(search_term),
                    Accessory.notes.contains(search_term)
                )
            )
            
            accessories = accessory_query.all()
    
    return render_template('search.html', 
                         phones=phones, 
                         accessories=accessories,
                         search_term=search_term,
                         search_type=search_type,
                         condition=condition)

@app.route('/sales')
@login_required
def list_sales():
    """List all sales with filtering"""
    from datetime import datetime, timedelta
    
    # Get filter parameters
    filter_type = request.args.get('filter_type', 'all')
    filter_date = request.args.get('filter_date', '')
    filter_month_year = request.args.get('filter_month_year', '')
    filter_month_month = request.args.get('filter_month_month', '')
    filter_year = request.args.get('filter_year', '')
    
    # Base query
    query = Sale.query
    
    # Apply filters
    if filter_type == 'day' and filter_date:
        try:
            filter_date_obj = datetime.strptime(filter_date, '%Y-%m-%d')
            next_day = filter_date_obj + timedelta(days=1)
            query = query.filter(
                Sale.date_created >= filter_date_obj,
                Sale.date_created < next_day
            )
        except ValueError:
            pass
    elif filter_type == 'month' and filter_month_year and filter_month_month:
        try:
            month_start = datetime(int(filter_month_year), int(filter_month_month), 1)
            if int(filter_month_month) == 12:
                next_month = datetime(int(filter_month_year) + 1, 1, 1)
            else:
                next_month = datetime(int(filter_month_year), int(filter_month_month) + 1, 1)
            query = query.filter(
                Sale.date_created >= month_start,
                Sale.date_created < next_month
            )
        except ValueError:
            pass
    elif filter_type == 'year' and filter_year:
        try:
            year_start = datetime(int(filter_year), 1, 1)
            year_end = datetime(int(filter_year) + 1, 1, 1)
            query = query.filter(
                Sale.date_created >= year_start,
                Sale.date_created < year_end
            )
        except ValueError:
            pass
    
    # Get filtered sales
    sales = query.order_by(Sale.date_created.desc()).all()
    
    # Calculate summary statistics for filtered results
    total_sales_count = len(sales)
    total_sales_amount = sum(sale.total_amount for sale in sales)
    total_sales_subtotal = sum(sale.subtotal for sale in sales)
    total_vat_amount = sum(sale.vat_amount for sale in sales)
    
    # Get current date for default values
    now = datetime.now()
    current_year = now.year
    current_month = now.month
    
    return render_template('list_sales.html', 
                         sales=sales,
                         filter_type=filter_type,
                         filter_date=filter_date,
                         filter_month_year=filter_month_year,
                         filter_month_month=filter_month_month,
                         filter_year=filter_year,
                         total_sales_count=total_sales_count,
                         total_sales_amount=total_sales_amount,
                         total_sales_subtotal=total_sales_subtotal,
                         total_vat_amount=total_vat_amount,
                         current_year=current_year,
                         current_month=current_month)

# Invoices route removed - replaced by sales system



@app.route('/inventory_summary')
@login_required
def inventory_summary():
    # Get total phones count
    total_phones = Phone.query.count()
    
    # Get new and used phones counts
    new_phones_count = Phone.query.filter_by(condition='new').count()
    used_phones_count = Phone.query.filter_by(condition='used').count()
    
    # Get values for new and used phones
    new_phones = Phone.query.filter_by(condition='new').all()
    used_phones = Phone.query.filter_by(condition='used').all()
    
    # Calculate purchase and selling values
    new_phones_purchase_value = sum(phone.purchase_price for phone in new_phones)
    new_phones_selling_value = sum(phone.selling_price for phone in new_phones)
    new_phones_profit = new_phones_selling_value - new_phones_purchase_value
    
    used_phones_purchase_value = sum(phone.purchase_price for phone in used_phones)
    used_phones_selling_value = sum(phone.selling_price for phone in used_phones)
    used_phones_profit = used_phones_selling_value - used_phones_purchase_value
    
    # Total values
    total_purchase_value = new_phones_purchase_value + used_phones_purchase_value
    total_selling_value = new_phones_selling_value + used_phones_selling_value
    total_profit = total_selling_value - total_purchase_value
    
    # Get phone type summary (new vs used)
    phone_type_summary = db.session.query(
        Phone.condition,
        func.count(Phone.id).label('total_phones'),
        func.sum(Phone.purchase_price).label('total_purchase_value'),
        func.sum(Phone.selling_price).label('total_selling_value'),
        func.avg(Phone.selling_price).label('average_price')
    ).group_by(Phone.condition).all()
    
    # Get brand and model summary within each phone type
    new_phones_brand_summary = db.session.query(
        Phone.brand,
        Phone.model,
        func.count(Phone.id).label('total_phones'),
        func.sum(Phone.purchase_price).label('total_purchase_value'),
        func.sum(Phone.selling_price).label('total_selling_value'),
        func.avg(Phone.selling_price).label('average_price')
    ).filter_by(condition='new').group_by(Phone.brand, Phone.model).all()
    
    used_phones_brand_summary = db.session.query(
        Phone.brand,
        Phone.model,
        func.count(Phone.id).label('total_phones'),
        func.sum(Phone.purchase_price).label('total_purchase_value'),
        func.sum(Phone.selling_price).label('total_selling_value'),
        func.avg(Phone.selling_price).label('average_price')
    ).filter_by(condition='used').group_by(Phone.brand, Phone.model).all()
    
    return render_template('inventory_summary.html',
                         total_phones=total_phones,
                         new_phones_count=new_phones_count,
                         used_phones_count=used_phones_count,
                         new_phones_purchase_value=new_phones_purchase_value,
                         new_phones_selling_value=new_phones_selling_value,
                         new_phones_profit=new_phones_profit,
                         used_phones_purchase_value=used_phones_purchase_value,
                         used_phones_selling_value=used_phones_selling_value,
                         used_phones_profit=used_phones_profit,
                         total_purchase_value=total_purchase_value,
                         total_selling_value=total_selling_value,
                         total_profit=total_profit,
                         phone_type_summary=phone_type_summary,
                         new_phones_brand_summary=new_phones_brand_summary,
                         used_phones_brand_summary=used_phones_brand_summary)

# AJAX routes for phone types and accessory categories
@app.route('/add_phone_type_ajax', methods=['POST'])
@login_required
def add_phone_type_ajax():
    """Add a new phone type via AJAX"""
    try:
        data = request.get_json()
        brand = data.get('brand', '').strip()
        model = data.get('model', '').strip()
        
        if not brand or not model:
            return jsonify({'success': False, 'message': 'يرجى إدخال العلامة التجارية والموديل'})
        
        # Check if phone type already exists
        existing = PhoneType.query.filter_by(brand=brand, model=model).first()
        if existing:
            return jsonify({'success': False, 'message': 'هذا الموديل موجود بالفعل'})
        
        # Create new phone type
        phone_type = PhoneType(brand=brand, model=model)
        db.session.add(phone_type)
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'تم إضافة {brand} {model} بنجاح'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'حدث خطأ: {str(e)}'})

@app.route('/delete_phone_type_ajax', methods=['POST'])
@login_required
def delete_phone_type_ajax():
    """Delete a phone type via AJAX"""
    try:
        data = request.get_json()
        brand = data.get('brand', '').strip()
        model = data.get('model', '').strip()
        
        if not brand or not model:
            return jsonify({'success': False, 'message': 'يرجى اختيار العلامة التجارية والموديل'})
        
        # Check if phone type exists
        phone_type = PhoneType.query.filter_by(brand=brand, model=model).first()
        if not phone_type:
            return jsonify({'success': False, 'message': 'الموديل غير موجود'})
        
        # Check if any phones are using this type
        phones_using_type = Phone.query.filter_by(brand=brand, model=model).count()
        if phones_using_type > 0:
            return jsonify({'success': False, 'message': f'لا يمكن حذف هذا الموديل لأنه مستخدم في {phones_using_type} هاتف'})
        
        # Delete the phone type
        db.session.delete(phone_type)
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'تم حذف {brand} {model} بنجاح'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'حدث خطأ: {str(e)}'})

@app.route('/get_phone_types_ajax')
@login_required
def get_phone_types_ajax():
    """Get phone types for AJAX"""
    try:
        phone_types = PhoneType.query.all()
        brands = {}
        for phone_type in phone_types:
            if phone_type.brand not in brands:
                brands[phone_type.brand] = []
            brands[phone_type.brand].append(phone_type.model)
        
        return jsonify({'success': True, 'brands': brands})
    except Exception as e:
        return jsonify({'success': False, 'message': f'حدث خطأ: {str(e)}'})

@app.route('/add_accessory_category_ajax', methods=['POST'])
@login_required
def add_accessory_category_ajax():
    """Add a new accessory category via AJAX"""
    try:
        data = request.get_json()
        arabic_name = data.get('name', '').strip()
        
        if not arabic_name:
            return jsonify({'success': False, 'message': 'يرجى إدخال اسم الفئة'})
        
        # Generate English name from Arabic name
        english_name = arabic_name.lower().replace(' ', '_').replace('أ', 'a').replace('ب', 'b').replace('ت', 't').replace('ث', 'th').replace('ج', 'j').replace('ح', 'h').replace('خ', 'kh').replace('د', 'd').replace('ذ', 'th').replace('ر', 'r').replace('ز', 'z').replace('س', 's').replace('ش', 'sh').replace('ص', 's').replace('ض', 'd').replace('ط', 't').replace('ظ', 'z').replace('ع', 'a').replace('غ', 'gh').replace('ف', 'f').replace('ق', 'q').replace('ك', 'k').replace('ل', 'l').replace('م', 'm').replace('ن', 'n').replace('ه', 'h').replace('و', 'w').replace('ي', 'y').replace('ة', 'h').replace('ى', 'a').replace('ئ', 'a')
        
        # Check if category already exists (check both name and arabic_name)
        existing = AccessoryCategory.query.filter(
            (AccessoryCategory.name == english_name) | 
            (AccessoryCategory.arabic_name == arabic_name)
        ).first()
        if existing:
            return jsonify({'success': False, 'message': 'هذه الفئة موجودة بالفعل'})
        
        # Create new category
        category = AccessoryCategory(name=english_name, arabic_name=arabic_name)
        db.session.add(category)
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'تم إضافة فئة {arabic_name} بنجاح'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'حدث خطأ: {str(e)}'})

@app.route('/delete_accessory_category_ajax', methods=['POST'])
@login_required
def delete_accessory_category_ajax():
    """Delete an accessory category via AJAX"""
    try:
        data = request.get_json()
        arabic_name = data.get('name', '').strip()
        
        if not arabic_name:
            return jsonify({'success': False, 'message': 'يرجى اختيار الفئة'})
        
        # Check if category exists (search by arabic_name)
        category = AccessoryCategory.query.filter_by(arabic_name=arabic_name).first()
        if not category:
            return jsonify({'success': False, 'message': 'الفئة غير موجودة'})
        
        # Check if any accessories are using this category
        accessories_using_category = Accessory.query.filter_by(category=category.name).count()
        if accessories_using_category > 0:
            return jsonify({'success': False, 'message': f'لا يمكن حذف هذه الفئة لأنها مستخدمة في {accessories_using_category} أكسسوار'})
        
        # Delete the category
        db.session.delete(category)
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'تم حذف فئة {arabic_name} بنجاح'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'حدث خطأ: {str(e)}'})

@app.route('/get_accessory_categories_ajax')
@login_required
def get_accessory_categories_ajax():
    """Get accessory categories for AJAX"""
    try:
        categories = AccessoryCategory.query.all()
        category_list = [category.arabic_name for category in categories]
        return jsonify({'success': True, 'categories': category_list})
    except Exception as e:
        return jsonify({'success': False, 'message': f'حدث خطأ: {str(e)}'})

# sell_phone route removed - replaced by comprehensive sales system

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Create tables if they do not exist
        create_admin_user()  # Create admin user on startup if missing
        create_default_phone_types()  # Create default phone types if they don't exist
        create_default_accessory_categories()  # Create default accessory categories if they don't exist
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5001)
    args = parser.parse_args()
    app.run(debug=True, port=args.port) 