from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import String, Integer, DateTime, Enum, Text, Float, Index, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProductStatus(str, PyEnum):
    PENDING = "pending"          # щойно з Telegram, чекає твого approve
    APPROVED = "approved"        # ти підтвердив, в черзі на AI
    GENERATING = "generating"    # AI працює
    READY = "ready"              # AI-фото готові, можна публікувати
    LIVE = "live"                # на сайті
    REJECTED = "rejected"        # ти відхилив
    FAILED = "failed"            # помилка генерації


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_message_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    price_uah: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Шляхи до файлів (відносно media_dir)
    original_photo: Mapped[str] = mapped_column(String(500))  # фото від постачальника
    generated_photo: Mapped[str | None] = mapped_column(String(500), nullable=True)  # AI try-on результат
    extra_photos: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: ["path1", "path2", ...]
    size_chart: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON: size chart table

    article_1c: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "women" | "men"
    stock: Mapped[int] = mapped_column(Integer, default=0)

    title_ua: Mapped[str | None] = mapped_column(Text, nullable=True)
    title_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)   # Футболка, Куртка, Штани…
    season: Mapped[str | None] = mapped_column(String(100), nullable=True)     # Весна/Літо 2025, Зима 2025…
    match_type: Mapped[str | None] = mapped_column(String(10), nullable=True)  # exact | approx

    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus), default=ProductStatus.PENDING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    birthday: Mapped[str | None] = mapped_column(String(20), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_verified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OTPCode(Base):
    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str] = mapped_column(String(10))
    purpose: Mapped[str] = mapped_column(String(20))  # "verify" | "login"
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OrderStatus(str, PyEnum):
    NEW       = "new"
    CONFIRMED = "confirmed"
    SHIPPED   = "shipped"
    DONE      = "done"
    CANCELLED = "cancelled"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    name:  Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(255))
    delivery_type: Mapped[str] = mapped_column(String(20))  # "nova_poshta" | "pickup"
    city:      Mapped[str | None] = mapped_column(String(255), nullable=True)
    np_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_uah: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), default=OrderStatus.NEW
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_title: Mapped[str] = mapped_column(String(500))
    size: Mapped[str | None] = mapped_column(String(20), nullable=True)
    price_uah: Mapped[float] = mapped_column(Float)
    qty: Mapped[int] = mapped_column(Integer, default=1)


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    totp_secret: Mapped[str | None] = mapped_column(String(32), nullable=True)
    backup_codes: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admins.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(50))
    ip_address: Mapped[str] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
