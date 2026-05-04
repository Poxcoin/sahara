from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import String, Integer, DateTime, Enum, Text, Float
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

    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus), default=ProductStatus.PENDING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
