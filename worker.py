import os
from redis import Redis
from rq import Worker, Queue, Connection

listen = ['default']

redis_host = os.getenv('REDIS_HOST', 'redis')  # Nom du service Redis dans votre docker-compose.yml
conn = Redis(host=redis_host)

if __name__ == '__main__':
    with Connection(conn):
        worker = Worker(list(map(Queue, listen)))
        worker.work()
