import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  vus: 10,
  duration: "30s",
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<1000"]
  }
};

const API_URL = __ENV.API_URL || "http://localhost:8000";
const NOTIFICATION_URL = __ENV.NOTIFICATION_URL || "http://localhost:8001";

function jsonHeaders(token) {
  const headers = { "Content-Type": "application/json" };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

export function setup() {
  const suffix = `${Date.now()}_${Math.floor(Math.random() * 100000)}`;
  const seller = `load_seller_${suffix}`;
  const buyer = `load_buyer_${suffix}`;

  check(http.post(`${API_URL}/auth/register`, JSON.stringify({ username: seller, password: "secret123", role: "SELLER" }), { headers: jsonHeaders() }), {
    "seller registered": (r) => r.status === 201
  });
  check(http.post(`${API_URL}/auth/register`, JSON.stringify({ username: buyer, password: "secret123", role: "USER" }), { headers: jsonHeaders() }), {
    "buyer registered": (r) => r.status === 201
  });

  const sellerLogin = http.post(`${API_URL}/auth/login`, JSON.stringify({ username: seller, password: "secret123" }), { headers: jsonHeaders() });
  const buyerLogin = http.post(`${API_URL}/auth/login`, JSON.stringify({ username: buyer, password: "secret123" }), { headers: jsonHeaders() });
  check(sellerLogin, { "seller logged in": (r) => r.status === 200 });
  check(buyerLogin, { "buyer logged in": (r) => r.status === 200 });

  const productResponse = http.post(
    `${API_URL}/products`,
    JSON.stringify({
      name: `Load product ${suffix}`,
      description: "Load test product",
      price: 25.99,
      stock: 1000,
      category: "load",
      status: "ACTIVE"
    }),
    { headers: jsonHeaders(sellerLogin.json("access_token")) }
  );
  check(productResponse, { "product created": (r) => r.status === 201 });

  const orderResponse = http.post(
    `${API_URL}/orders`,
    JSON.stringify({ items: [{ product_id: productResponse.json("id"), quantity: 1 }] }),
    { headers: jsonHeaders(buyerLogin.json("access_token")) }
  );
  check(orderResponse, { "order created": (r) => r.status === 201 });

  return {
    buyerToken: buyerLogin.json("access_token"),
    orderId: orderResponse.json("id")
  };
}

export default function (data) {
  const health = http.get(`${API_URL}/health`);
  check(health, { "api health ok": (r) => r.status === 200 });

  const products = http.get(`${API_URL}/products?size=20&category=load`, { headers: jsonHeaders(data.buyerToken) });
  check(products, { "products listed": (r) => r.status === 200 });

  const notifications = http.get(`${NOTIFICATION_URL}/notifications/orders/${data.orderId}`);
  check(notifications, { "notifications listed": (r) => r.status === 200 });

  sleep(1);
}
