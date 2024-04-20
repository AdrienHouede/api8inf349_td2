""" $env:FLASK_DEBUG = "True"
$env:FLASK_APP = "api8inf349"
$env:REDIS_URL = "redis://localhost"
$env:DB_HOST = "localhost"
$env:DB_USER = "user"
$env:DB_PASSWORD = "pass"
$env:DB_PORT = "5432"
$env:DB_NAME = "api8inf349" """

import click
import redis
import os
from flask import Flask, jsonify, request, render_template, redirect, url_for
import peewee, requests, click, json
from flask.cli import with_appcontext
from flask_redis import FlaskRedis
from rq import Queue

db = peewee.PostgresqlDatabase(
    "api8inf349",
    user="user",
    password="pass",
    host="database",
    port=5432
)

@click.command("init-db")
@with_appcontext
def init_db_command():
    db.create_tables([ShoppingRow, Orders])
    fetch_products_from_url()
    print("Initialized the database.")

class ShoppingRow(peewee.Model):
    id = peewee.PrimaryKeyField()
    name = peewee.CharField()
    type = peewee.CharField(default="")
    description = peewee.CharField()
    image = peewee.CharField(default="")
    height = peewee.IntegerField(default=0)
    weight = peewee.IntegerField(default=0)
    price = peewee.FloatField()
    in_stock = peewee.BooleanField()

    class Meta:
        database = db

class Orders(peewee.Model):
    id = peewee.PrimaryKeyField()
    total_price = peewee.FloatField()
    email = peewee.CharField()
    credit_card = peewee.TextField(default={})
    shipping_information = peewee.TextField(default={})
    paid = peewee.BooleanField(default=False)
    transaction = peewee.TextField(default={})
    products = peewee.TextField(default={})
    shipping_price = peewee.FloatField()

    class Meta:
        database = db

app = Flask(__name__)

redis_client = redis.StrictRedis(host='redis', port=6379, db=0)
redis_store = FlaskRedis(app)

app.cli.add_command(init_db_command)

def fetch_products_from_url():
    url = "http://dimprojetu.uqac.ca/~jgnault/shops/products/"
    response = requests.get(url)
    if response.status_code == 200:
        products_data = response.json().get("products", [])
        for product in products_data:
            # Vérifier si les valeurs ne sont pas nulles ou vides
            product_name = product.get("name", "").replace("\x00", "")
            product_type = product.get("type", "").replace("\x00", "")
            description = product.get("description", "").replace("\x00", "")
            image = product.get("image", "").replace("\x00", "")
            height = int(product.get("height", 0))
            weight = int(product.get("weight", 0))
            price = float(product["price"])
            in_stock = 0 if not product["in_stock"] else 1
            ShoppingRow.create(
                name=product_name,
                type=product_type,
                description=description,
                image=image,
                height=height,
                weight=weight,
                price=price,
                in_stock=in_stock
            )
        print("Products data fetched and stored locally.")
    else:
        print("Failed to fetch products data from the URL.")

'''def process_payment(order_id, credit_card, amount_charged):
    payment_url = "http://dimprojetu.uqac.ca/~jgnault/shops/pay/"
    credit_card_data = json.loads(credit_card)
    payload = {
        "credit_card": credit_card_data,
        "amount_charged": amount_charged
    }
    response = requests.post(payment_url, json=payload)
    if response.status_code != 200:
        error_message = response.json()["errors"]["credit_card"]["name"]
        raise ValueError(error_message)
    return response.json()'''

def process_payment_task(order_id, credit_card, amount_charged):
    payment_url = "http://dimprojetu.uqac.ca/~jgnault/shops/pay/"
    credit_card_data = json.loads(credit_card)
    payload = {
        "credit_card": credit_card_data,
        "amount_charged": amount_charged
    }
    response = requests.post(payment_url, json=payload)
    return response.json()

queue = Queue(connection=redis_client)
def enqueue_payment_process(order_id, credit_card, amount_charged):
    job = queue.enqueue(process_payment_task, order_id, credit_card, amount_charged)
    while job.result is None:
        pass
    result = job.result
    return result


def cache_paid_order(order_id, order_details):
    redis_key = f"order:{order_id}"
    redis_client.set(redis_key, json.dumps(order_details))

@app.route("/")
def all_product():
    fetch_products_from_url()
    return render_template("index.html", shopping_list=ShoppingRow.select())

@app.route("/order", methods=["POST"])
def new_order():
    products = request.form.getlist("products[]")
    quantities = request.form.getlist("quantities[]")
    email = request.form.get("email")
    country = request.form.get("country")
    address = request.form.get("address")
    postal_code = request.form.get("postal_code")
    city = request.form.get("city")
    province = request.form.get("province")

    missing_fields = []
    if not products:
        missing_fields.append("product_name")
    if not quantities:
        missing_fields.append("quantity")
    if not email:
        missing_fields.append("email")
    if not country:
        missing_fields.append("country")
    if not address:
        missing_fields.append("address")
    if not postal_code:
        missing_fields.append("postal_code")
    if not city:
        missing_fields.append("city")
    if not province:
        missing_fields.append("province")

    if missing_fields:
        error_response = {
            "errors": {
                "order": {
                    "code": "missing-fields",
                    "name": "One or more fields that are required are missing",
                    "missing_fields": missing_fields
                }
            }
        }
        return jsonify(error_response), 422

    order_details = {}
    total_price = 0
    total_weight = 0
    shipping_price = 0

    for product_name, quantity in zip(products, quantities):
        if not quantity or float(quantity) < 1:
            return jsonify({"error": "Invalid quantity"}), 422

        product_row = ShoppingRow.get_or_none(ShoppingRow.name == product_name)

        if product_row is None or product_row.in_stock == 0:
            return jsonify({"error": "Product not in stock"}), 422

        order_details[product_row.id] = {"quantity": int(quantity)}
        total_price += product_row.price * int(quantity)
        total_weight += product_row.weight * int(quantity)

    if total_weight <= 500:
        shipping_price = 5
    elif total_weight <= 2000:
        shipping_price = 10
    else:
        shipping_price = 25

    total_price += shipping_price

    new_order = Orders.create(
        total_price=total_price,
        email=email,
        credit_card={},
        shipping_information=json.dumps({
            "country": country,
            "address": address,
            "postal_code": postal_code,
            "city": city,
            "province": province
        }),
        paid=False,
        transaction={},
        products=json.dumps(order_details),
        shipping_price=shipping_price
    )

    return render_template("payment_form.html")


@app.route("/payment_order", methods=["POST"])
def payment_order():
    last_order = Orders.select().order_by(Orders.id.desc()).first()
    order_row = Orders.get_or_none(Orders.id == last_order)
    products_json = order_row.products
    products_json_corrected = products_json.replace("'", '"')
    order_row.products = products_json_corrected

    if order_row is None:
        return jsonify({"message": "The specified command does not exist"}), 404

    if "credit_card" in request.form and ("shipping_information" in request.form or "email" in request.form):
        return jsonify({"error": "Payment and shipping information must be provided separately"}), 422
    
    if order_row.paid:
        return jsonify({"error": "The order has already been paid"}), 422

    card_name = request.form.get("card_name")
    card_number = request.form.get("card_number")
    card_expiry_month = request.form.get("card_expiry_month")
    card_expiry_year = request.form.get("card_expiry_year")
    card_cvv = request.form.get("card_cvv")

    missing_fields = []
    if not card_name:
        missing_fields.append("card_name")
    if not card_number:
        missing_fields.append("card_number")
    if not card_expiry_month:
        missing_fields.append("card_expiry_month")
    if not card_expiry_year:
        missing_fields.append("card_expiry_year")
    if not card_cvv:
        missing_fields.append("card_cvv")
    elif len(card_cvv) != 3 or not card_cvv.isdigit():
        missing_fields.append("card_cvv")

    if missing_fields:
        error_response = {
            "errors": {
                "payment": {
                    "code": "missing-fields",
                    "name": "One or more required fields are missing",
                    "missing_fields": missing_fields
                }
            }
        }
        return jsonify(error_response), 422

    order_row.total_price = order_row.total_price + order_row.shipping_price
    order_row.credit_card = json.dumps({
        "name": card_name,
        "number": card_number,
        "expiration_year": card_expiry_year,
        "cvv": card_cvv,
        "expiration_month": card_expiry_month
        
    })

    order_row.save()
    
    return redirect(url_for("get_order", order_id=order_row.id), code=302)

    
@app.route("/order/<int:order_id>", methods=["GET"])
def get_order(order_id):
    redis_key = f"order:{order_id}"
    cached_order = redis_client.get(redis_key)
    
    if cached_order:
        order_details = json.loads(cached_order)
    else:
        order_row = Orders.get_or_none(Orders.id == order_id)
        if order_row is None:
            return jsonify({"message": "La commande spécifiée n'existe pas"}), 404
        
        total_amount = order_row.total_price + order_row.shipping_price
        payment_result = enqueue_payment_process(order_id, order_row.credit_card, total_amount)
        products_json = order_row.products
        products_json_corrected = products_json.replace("'", '"')
        order_row.products = products_json_corrected
        transaction_data = payment_result.get("transaction", {})
        if transaction_data.get("success"):
            order_row.paid = True
            order_row.transaction = json.dumps(transaction_data)
            order_row.save()
            order_details = {
                "shipping_information": json.loads(order_row.shipping_information),
                "total_price": order_row.total_price,
                "email": order_row.email,
                "paid": order_row.paid,
                "products": json.loads(order_row.products),
                "credit_card": json.loads(order_row.credit_card),
                "transaction": json.loads(order_row.transaction),
                "shipping_price": order_row.shipping_price,
                "id": order_row.id
            }
            cache_paid_order(order_id, order_details)
        else:
            # Persist the payment error in the database
            error_code = payment_result.get("error_code", "")
            error_message = payment_result.get("error_message", "")
            transaction_data = {
                "success": False,
                "error": {
                    "code": error_code,
                    "name": error_message
                },
                "amount_charged": payment_result.get("amount_charged", 0)
            }
            order_row.paid = False
            order_row.transaction = json.dumps(transaction_data)
            order_row.save()
            order_details = {
                "shipping_information": json.loads(order_row.shipping_information),
                "total_price": order_row.total_price,
                "email": order_row.email,
                "paid": order_row.paid,
                "products": json.loads(order_row.products),
                "credit_card": json.loads(order_row.credit_card),
                "transaction": json.loads(order_row.transaction),
                "shipping_price": order_row.shipping_price,
                "id": order_row.id
            }
    
    #return jsonify({"order": order_details}), 200
    return render_template("order_details.html", order=order_details)


@app.route("/delete/<int:identifier>", methods=["GET"])
def get_by_id(identifier: int):
    shopping_row = ShoppingRow.get_or_none(ShoppingRow.id == identifier)
    if not shopping_row:
        return "Il n'existe pas"
    shopping_row.delete_instance()
    return render_template("index.html", shopping_list=ShoppingRow.select())

@app.route("/cached_orders")
def get_cached_orders():
    try:
        cached_order_keys = redis_client.keys("order:*")
        cached_order_ids = []
        for key in cached_order_keys:
            order_id = key.decode("utf-8").split(":")[1]
            cached_order_ids.append(order_id)
        return jsonify({"orders": cached_order_ids})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
