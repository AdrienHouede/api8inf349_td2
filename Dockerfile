FROM python:3.9

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=api8inf349.py

EXPOSE 5000

EXPOSE 6379

CMD ["sh", "-c", "flask run --host=0.0.0.0 --port=5000 & rq worker --with-scheduler"]
