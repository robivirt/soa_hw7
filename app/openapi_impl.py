from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Optional

from fastapi import Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import create_token, hash_password, verify_password, decode_token
from app.db import SessionLocal
from app.errors import ApiError
from app.generated_security import Principal, current_principal
from app.models import Order, OrderItem, Product, PromoCode, User, UserOperation
from app.settings import settings

from generated_server.apis.auth_api_base import BaseAuthApi
from generated_server.apis.orders_api_base import BaseOrdersApi
from generated_server.apis.products_api_base import BaseProductsApi
from generated_server.apis.promo_codes_api_base import BasePromoCodesApi
from generated_server.models.login_request import LoginRequest
from generated_server.models.order_create import OrderCreate
from generated_server.models.order_item_response import OrderItemResponse
from generated_server.models.order_response import OrderResponse
from generated_server.models.order_update import OrderUpdate
from generated_server.models.product_create import ProductCreate
from generated_server.models.product_page import ProductPage
from generated_server.models.product_response import ProductResponse
from generated_server.models.product_status import ProductStatus
from generated_server.models.product_update import ProductUpdate
from generated_server.models.promo_code_create import PromoCodeCreate
from generated_server.models.promo_code_response import PromoCodeResponse
from generated_server.models.refresh_request import RefreshRequest
from generated_server.models.register_request import RegisterRequest
from generated_server.models.token_pair import TokenPair
from generated_server.models.user_response import UserResponse


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def as_number(value: Decimal) -> float:
    return float(money(value))


def created(model) -> JSONResponse:
    return JSONResponse(status_code=201, content=jsonable_encoder(model.to_dict()))


def require_roles(*roles: str) -> Principal:
    principal = current_principal()
    if principal.role not in roles:
        raise ApiError(403, "ACCESS_DENIED", "Access denied")
    return principal


def ensure_product_access(principal: Principal, product: Product) -> None:
    if principal.role == "ADMIN":
        return
    if principal.role == "SELLER" and product.seller_id == principal.user_id:
        return
    raise ApiError(403, "ACCESS_DENIED", "Access denied")


def ensure_order_access(principal: Principal, order: Order) -> None:
    if principal.role == "ADMIN":
        return
    if principal.role == "USER" and order.user_id == principal.user_id:
        return
    raise ApiError(403, "ORDER_OWNERSHIP_VIOLATION", "Order belongs to another user")


def product_response(product: Product) -> ProductResponse:
    return ProductResponse(
        id=str(product.id),
        name=product.name,
        description=product.description,
        price=as_number(product.price),
        stock=product.stock,
        category=product.category,
        status=product.status,
        seller_id=str(product.seller_id),
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def order_response(order: Order) -> OrderResponse:
    return OrderResponse(
        id=str(order.id),
        user_id=str(order.user_id),
        status=order.status,
        items=[
            OrderItemResponse(
                id=str(item.id),
                product_id=str(item.product_id),
                quantity=item.quantity,
                price_at_order=as_number(item.price_at_order),
            )
            for item in order.items
        ],
        promo_code=order.promo_code.code if order.promo_code else None,
        total_amount=as_number(order.total_amount),
        discount_amount=as_number(order.discount_amount),
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def promo_response(promo: PromoCode) -> PromoCodeResponse:
    return PromoCodeResponse(
        id=str(promo.id),
        code=promo.code,
        discount_type=promo.discount_type,
        discount_value=as_number(promo.discount_value),
        min_order_amount=as_number(promo.min_order_amount),
        max_uses=promo.max_uses,
        current_uses=promo.current_uses,
        valid_from=promo.valid_from,
        valid_until=promo.valid_until,
        active=promo.active,
    )


def user_response(user: User) -> UserResponse:
    return UserResponse(id=str(user.id), username=user.username, role=user.role, created_at=user.created_at)


def uuid_from(value: str) -> uuid.UUID:
    return uuid.UUID(str(value))


def check_rate_limit(db: Session, user_id: uuid.UUID, operation_type: str) -> None:
    last_operation = db.scalar(
        select(UserOperation)
        .where(UserOperation.user_id == user_id, UserOperation.operation_type == operation_type)
        .order_by(UserOperation.created_at.desc())
        .limit(1)
    )
    if last_operation is None:
        return
    allowed_at = aware(last_operation.created_at) + timedelta(minutes=settings.order_rate_limit_minutes)
    if utcnow() < allowed_at:
        raise ApiError(
            429,
            "ORDER_LIMIT_EXCEEDED",
            "Order operation rate limit exceeded",
            {"retry_after": allowed_at.isoformat()},
        )


def aggregate_items(items: Iterable) -> dict[uuid.UUID, int]:
    quantities: dict[uuid.UUID, int] = {}
    for item in items:
        product_id = uuid_from(item.product_id)
        quantities[product_id] = quantities.get(product_id, 0) + item.quantity
    return quantities


def reserve_products(db: Session, items: Iterable) -> list[tuple[Product, int]]:
    reserved: list[tuple[Product, int]] = []
    insufficient: list[dict[str, Any]] = []
    for product_id, quantity in aggregate_items(items).items():
        product = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
        if product is None:
            raise ApiError(404, "PRODUCT_NOT_FOUND", "Product not found", {"product_id": str(product_id)})
        if product.status != ProductStatus.ACTIVE.value:
            raise ApiError(409, "PRODUCT_INACTIVE", "Product is inactive", {"product_id": str(product_id)})
        if product.stock < quantity:
            insufficient.append({"product_id": str(product_id), "requested": quantity, "available": product.stock})
        reserved.append((product, quantity))

    if insufficient:
        raise ApiError(409, "INSUFFICIENT_STOCK", "Insufficient stock", {"products": insufficient})

    for product, quantity in reserved:
        product.stock -= quantity
    return reserved


def validate_promo(db: Session, code: str) -> PromoCode:
    promo = db.scalar(select(PromoCode).where(PromoCode.code == code).with_for_update())
    now = utcnow()
    if (
        promo is None
        or not promo.active
        or promo.current_uses >= promo.max_uses
        or now < aware(promo.valid_from)
        or now > aware(promo.valid_until)
    ):
        raise ApiError(422, "PROMO_CODE_INVALID", "Promo code is invalid")
    return promo


def calculate_discount(total: Decimal, promo: PromoCode) -> Decimal:
    if promo.discount_type == "PERCENTAGE":
        return money(min(total * promo.discount_value / Decimal("100"), total * Decimal("0.70")))
    return money(min(promo.discount_value, total))


def apply_promo_to_total(total: Decimal, promo: PromoCode) -> tuple[Decimal, Decimal]:
    if total < promo.min_order_amount:
        raise ApiError(422, "PROMO_CODE_MIN_AMOUNT", "Order amount is below promo code minimum")
    discount = calculate_discount(total, promo)
    return money(total - discount), discount


class AuthApiImpl(BaseAuthApi):
    async def auth_register_post(self, register_request: RegisterRequest):
        with SessionLocal() as db:
            exists = db.scalar(select(User).where(User.username == register_request.username))
            if exists:
                raise ApiError(400, "VALIDATION_ERROR", "Username already exists", {"fields": ["username"]})
            user = User(
                username=register_request.username,
                password_hash=hash_password(register_request.password),
                role=register_request.role.value,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return created(user_response(user))

    async def auth_login_post(self, login_request: LoginRequest) -> TokenPair:
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username == login_request.username))
            if user is None or not verify_password(login_request.password, user.password_hash):
                raise ApiError(401, "TOKEN_INVALID", "Invalid credentials")
            return TokenPair(
                access_token=create_token(user, "access"),
                refresh_token=create_token(user, "refresh"),
                token_type="bearer",
            )

    async def auth_refresh_post(self, refresh_request: RefreshRequest) -> TokenPair:
        payload = decode_token(refresh_request.refresh_token, "refresh")
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.id == uuid_from(payload["sub"])))
            if user is None:
                raise ApiError(401, "REFRESH_TOKEN_INVALID", "Refresh token user does not exist")
            return TokenPair(
                access_token=create_token(user, "access"),
                refresh_token=create_token(user, "refresh"),
                token_type="bearer",
            )


class ProductsApiImpl(BaseProductsApi):
    async def products_post(self, product_create: ProductCreate):
        principal = require_roles("SELLER", "ADMIN")
        seller_id = principal.user_id if principal.role == "SELLER" else uuid_from(product_create.seller_id or principal.user_id)
        with SessionLocal() as db:
            product = Product(
                name=product_create.name,
                description=product_create.description,
                price=Decimal(str(product_create.price)),
                stock=product_create.stock,
                category=product_create.category,
                status=product_create.status.value,
                seller_id=seller_id,
            )
            db.add(product)
            db.commit()
            db.refresh(product)
            return created(product_response(product))

    async def products_get(
        self,
        page: Optional[int],
        size: Optional[int],
        status: Optional[ProductStatus],
        category: Optional[str],
    ) -> ProductPage:
        require_roles("USER", "SELLER", "ADMIN")
        page = 0 if page is None else page
        size = 20 if size is None else size
        with SessionLocal() as db:
            query = select(Product)
            count_query = select(func.count()).select_from(Product)
            if status is not None:
                query = query.where(Product.status == status.value)
                count_query = count_query.where(Product.status == status.value)
            if category is not None:
                query = query.where(Product.category == category)
                count_query = count_query.where(Product.category == category)
            total = db.scalar(count_query) or 0
            products = db.scalars(query.order_by(Product.created_at.desc()).offset(page * size).limit(size)).all()
            return ProductPage(
                items=[product_response(product) for product in products],
                total_elements=total,
                page=page,
                size=size,
            )

    async def products_id_get(self, id: str) -> ProductResponse:
        require_roles("USER", "SELLER", "ADMIN")
        with SessionLocal() as db:
            product = db.get(Product, uuid_from(id))
            if product is None:
                raise ApiError(404, "PRODUCT_NOT_FOUND", "Product not found")
            return product_response(product)

    async def products_id_put(self, id: str, product_update: ProductUpdate) -> ProductResponse:
        principal = require_roles("SELLER", "ADMIN")
        with SessionLocal() as db:
            product = db.scalar(select(Product).where(Product.id == uuid_from(id)).with_for_update())
            if product is None:
                raise ApiError(404, "PRODUCT_NOT_FOUND", "Product not found")
            ensure_product_access(principal, product)
            product.name = product_update.name
            product.description = product_update.description
            product.price = Decimal(str(product_update.price))
            product.stock = product_update.stock
            product.category = product_update.category
            product.status = product_update.status.value
            db.commit()
            db.refresh(product)
            return product_response(product)

    async def products_id_delete(self, id: str) -> Response:
        principal = require_roles("SELLER", "ADMIN")
        with SessionLocal() as db:
            product = db.scalar(select(Product).where(Product.id == uuid_from(id)).with_for_update())
            if product is None:
                raise ApiError(404, "PRODUCT_NOT_FOUND", "Product not found")
            ensure_product_access(principal, product)
            product.status = ProductStatus.ARCHIVED.value
            db.commit()
            return Response(status_code=204)


class PromoCodesApiImpl(BasePromoCodesApi):
    async def promo_codes_post(self, promo_code_create: PromoCodeCreate):
        require_roles("SELLER", "ADMIN")
        with SessionLocal() as db:
            promo = PromoCode(
                code=promo_code_create.code,
                discount_type=promo_code_create.discount_type.value,
                discount_value=Decimal(str(promo_code_create.discount_value)),
                min_order_amount=Decimal(str(promo_code_create.min_order_amount)),
                max_uses=promo_code_create.max_uses,
                valid_from=promo_code_create.valid_from,
                valid_until=promo_code_create.valid_until,
                active=True if promo_code_create.active is None else promo_code_create.active,
            )
            db.add(promo)
            try:
                db.commit()
            except Exception:
                db.rollback()
                raise ApiError(400, "VALIDATION_ERROR", "Promo code already exists")
            db.refresh(promo)
            return created(promo_response(promo))


class OrdersApiImpl(BaseOrdersApi):
    async def orders_post(self, order_create: OrderCreate):
        principal = require_roles("USER", "ADMIN")
        with SessionLocal() as db:
            try:
                check_rate_limit(db, principal.user_id, "CREATE_ORDER")
                active_order = db.scalar(
                    select(Order)
                    .where(Order.user_id == principal.user_id, Order.status.in_(["CREATED", "PAYMENT_PENDING"]))
                    .limit(1)
                )
                if active_order:
                    raise ApiError(409, "ORDER_HAS_ACTIVE", "User already has an active order")

                reserved = reserve_products(db, order_create.items)
                subtotal = money(sum(product.price * quantity for product, quantity in reserved))
                promo = validate_promo(db, order_create.promo_code) if order_create.promo_code else None
                total = subtotal
                discount = Decimal("0.00")
                if promo is not None:
                    total, discount = apply_promo_to_total(subtotal, promo)
                    promo.current_uses += 1

                order = Order(
                    user_id=principal.user_id,
                    status="CREATED",
                    promo_code=promo,
                    total_amount=total,
                    discount_amount=discount,
                )
                order.items = [
                    OrderItem(product_id=product.id, quantity=quantity, price_at_order=product.price)
                    for product, quantity in reserved
                ]
                db.add(order)
                db.add(UserOperation(user_id=principal.user_id, operation_type="CREATE_ORDER"))
                db.commit()
                db.refresh(order)
                return created(order_response(order))
            except Exception:
                db.rollback()
                raise

    async def orders_id_get(self, id: str) -> OrderResponse:
        principal = require_roles("USER", "ADMIN")
        with SessionLocal() as db:
            order = db.scalar(
                select(Order)
                .where(Order.id == uuid_from(id))
                .options(selectinload(Order.items), selectinload(Order.promo_code))
            )
            if order is None:
                raise ApiError(404, "ORDER_NOT_FOUND", "Order not found")
            ensure_order_access(principal, order)
            return order_response(order)

    async def orders_id_put(self, id: str, order_update: OrderUpdate) -> OrderResponse:
        principal = require_roles("USER", "ADMIN")
        with SessionLocal() as db:
            try:
                order = db.scalar(
                    select(Order)
                    .where(Order.id == uuid_from(id))
                    .options(selectinload(Order.items), selectinload(Order.promo_code))
                    .with_for_update()
                )
                if order is None:
                    raise ApiError(404, "ORDER_NOT_FOUND", "Order not found")
                ensure_order_access(principal, order)
                if order.status != "CREATED":
                    raise ApiError(409, "INVALID_STATE_TRANSITION", "Only CREATED orders can be updated")
                check_rate_limit(db, order.user_id, "UPDATE_ORDER")

                for item in order.items:
                    product = db.scalar(select(Product).where(Product.id == item.product_id).with_for_update())
                    if product is not None:
                        product.stock += item.quantity

                reserved = reserve_products(db, order_update.items)
                subtotal = money(sum(product.price * quantity for product, quantity in reserved))
                promo = order.promo_code
                total = subtotal
                discount = Decimal("0.00")
                if promo is not None:
                    promo = db.scalar(select(PromoCode).where(PromoCode.id == promo.id).with_for_update())
                    if promo is None or not promo.active or utcnow() < aware(promo.valid_from) or utcnow() > aware(promo.valid_until):
                        raise ApiError(422, "PROMO_CODE_INVALID", "Promo code is invalid")
                    if subtotal >= promo.min_order_amount:
                        total, discount = apply_promo_to_total(subtotal, promo)
                    else:
                        promo.current_uses = max(0, promo.current_uses - 1)
                        promo = None

                order.items.clear()
                for product, quantity in reserved:
                    order.items.append(OrderItem(product_id=product.id, quantity=quantity, price_at_order=product.price))
                order.promo_code = promo
                order.total_amount = total
                order.discount_amount = discount
                db.add(UserOperation(user_id=order.user_id, operation_type="UPDATE_ORDER"))
                db.commit()
                db.refresh(order)
                return order_response(order)
            except Exception:
                db.rollback()
                raise

    async def orders_id_cancel_post(self, id: str) -> OrderResponse:
        principal = require_roles("USER", "ADMIN")
        with SessionLocal() as db:
            try:
                order = db.scalar(
                    select(Order)
                    .where(Order.id == uuid_from(id))
                    .options(selectinload(Order.items), selectinload(Order.promo_code))
                    .with_for_update()
                )
                if order is None:
                    raise ApiError(404, "ORDER_NOT_FOUND", "Order not found")
                ensure_order_access(principal, order)
                if order.status not in {"CREATED", "PAYMENT_PENDING"}:
                    raise ApiError(409, "INVALID_STATE_TRANSITION", "Order cannot be canceled from current state")

                for item in order.items:
                    product = db.scalar(select(Product).where(Product.id == item.product_id).with_for_update())
                    if product is not None:
                        product.stock += item.quantity
                if order.promo_code is not None:
                    promo = db.scalar(select(PromoCode).where(PromoCode.id == order.promo_code.id).with_for_update())
                    if promo is not None:
                        promo.current_uses = max(0, promo.current_uses - 1)
                order.status = "CANCELED"
                db.commit()
                db.refresh(order)
                return order_response(order)
            except Exception:
                db.rollback()
                raise
