from flask import Flask, request, Response, send_file
import jsonpickle
import base64
import io
import os
import redis
from minio import Minio
import uuid
import json

# Initialize the Flask application
app = Flask(__name__)
# redis_url = os.getenv('REDISTOGO_URL', 'redis://localhost:6379')

# redis = redis.from_url(redis_url)
redisHost = os.getenv("REDISTOGO_URL") or "localhost"
redisPort = os.getenv("REDISTOGO_PORT") or 6379

redis = redis.StrictRedis(host=redisHost, port=redisPort, db=0)

REDIS_KEY = "toWorkers"
BUCKET_NAME = "working"

minioHost = os.getenv("MINIO_HOST") or "localhost:9000"
minioUser = os.getenv("MINIO_USER") or "rootuser"
minioPasswd = os.getenv("MINIO_PASSWD") or "rootpass123"

MINIO_CLIENT = None
try:
    MINIO_CLIENT = Minio(minioHost, access_key=minioUser, secret_key=minioPasswd, secure=False)
except Exception as exp:
    print(f"Exception raised in worker loop: {str(exp)}")

@app.route('/apiv1/separate', methods=['POST'])
def seperate():
    post_data = json.loads(request.data)
    mp3_raw = post_data['mp3']
    mp3_encoded = mp3_raw.encode('utf-8')
    mp3_bytes = base64.b64decode(mp3_encoded)
    mp3_data = io.BytesIO(mp3_bytes)
    mp3_length = len(mp3_bytes)
    callback = post_data['callback']
    print("The callback is ", callback)
    found = MINIO_CLIENT.bucket_exists(BUCKET_NAME)
    if not found:
       MINIO_CLIENT.make_bucket(BUCKET_NAME)
    else:
       print("Bucket already exists")
       
    file_name = str(uuid.uuid4()) + ".mp3"
    print("Creating filename", file_name)
    MINIO_CLIENT.put_object(BUCKET_NAME, 
                  file_name,  
                  data=mp3_data, 
                  length=mp3_length)

    data = {
        'file_name' : file_name,
        'context' : callback
    }
    print("Pushing to queue", REDIS_KEY,data)
    count = redis.lpush(REDIS_KEY,json.dumps(data))
    redis.lpush("logging", f"Pushed file to queue {file_name}")
    print("Current queue length", count)
    response = {
        "hash": file_name, 
        "reason": "Song enqueued for separation"
    }
    response_pickled = jsonpickle.encode(response)
    return Response(response=response_pickled, status=200, mimetype="application/json")

@app.route('/apiv1/queue', methods=['GET'])
def queue():
    current_files = list(map(str,redis.lrange(REDIS_KEY, 0, -1)))
    response = {'queue' : current_files}
    response_pickled = jsonpickle.encode(response)
    return Response(response=response_pickled, status=200, mimetype="application/json")

@app.route('/apiv1/track', methods=['GET'])
def get_track():
    args = request.args.to_dict()
    file_id = args['file_id']
    component = args['component'] + ".mp3"
    MINIO_CLIENT.fget_object(file_id, component, component)
    return send_file(component,as_attachment=True)

@app.route('/apiv1/remove', methods=['GET'])
def remove():
    args = request.args.to_dict()
    file_id = args['file_id']
    found = MINIO_CLIENT.bucket_exists(file_id)
    if found:
        files = list(map(lambda x : x.object_name, MINIO_CLIENT.list_objects(file_id)))
        
        print("removing files", files, "from bucket", file_id)
        for file in files:
            MINIO_CLIENT.remove_object(file_id, file)
        MINIO_CLIENT.remove_bucket(file_id)
        response = {'response' : f"Removed bucket {file_id}"}
        response_pickled = jsonpickle.encode(response)
        return Response(response=response_pickled, status=200, mimetype="application/json")
    else:
        response = {'response' : f"Bucket {file_id} does not exist"}
        response_pickled = jsonpickle.encode(response)
        return Response(response=response_pickled, status=200, mimetype="application/json")

# start flask app
app.run(host="0.0.0.0", port=5000)