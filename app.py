from flask import Flask, request, jsonify
from flask_cors import CORS
import mysql.connector
import numpy as np
from ast import literal_eval
import requests
import json

app = Flask(__name__)
CORS(app) 

# MySQL 데이터베이스 연결 설정
db_config = {
    'host': 'localhost',
    'user': 'artause',
    'password': 'artause1234',
    'database': 'performance'
}

@app.route('/', methods=['GET'])
def main():
    return "helloguys"

@app.route('/api/data', methods=['GET'])
def get_data():
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT mt20id, prfnm, sty, poster FROM performances_emb LIMIT 50")
        results = cursor.fetchall()

        cursor.close()
        conn.close()

        return jsonify(results)

    except mysql.connector.Error as err:
        print(f"Error: {err}")
        return jsonify({"error": str(err)}), 500

def cosine_similarity(vec1, vec2):
    return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

@app.route('/userselect', methods=['GET'])
def user_select():
    plays = request.args.get('plays', '')
   
    if not plays:
        return jsonify({"error": "No plays selected"}), 400
    play_ids = plays.split(',')
   
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        # Fetch embeddings for selected plays
        placeholders = ', '.join(['%s'] * len(play_ids))
        cursor.execute(f"SELECT mt20id, embedding FROM performances_emb WHERE mt20id IN ({placeholders})", play_ids)
        selected_plays = cursor.fetchall()
        # Fetch all plays with embeddings
        cursor.execute("SELECT mt20id, prfnm, sty, poster, relateurl1, embedding FROM performances_emb WHERE prfstate = '공연중'")
        all_plays = cursor.fetchall()
        
        similar_plays_dict = {}  # Use a dictionary to store unique plays
        
        for selected_play in selected_plays:
            selected_embedding = np.array(literal_eval(selected_play['embedding']))
           
            similarities = []
            for play in all_plays:
                if play['mt20id'] != selected_play['mt20id']:
                    play_embedding = np.array(literal_eval(play['embedding']))
                    similarity = cosine_similarity(selected_embedding, play_embedding)
                    similarities.append((play, similarity))
           
            # Sort by similarity and get top 5
            similarities.sort(key=lambda x: x[1], reverse=True)
            top_similar = similarities[:1]
           
            for play, similarity in top_similar:
                # Only add the play if it's not already in the dictionary
                if play['mt20id'] not in similar_plays_dict:
                    similar_plays_dict[play['mt20id']] = {
                        'mt20id': play['mt20id'],
                        'prfnm': play['prfnm'],
                        'sty': play['sty'],
                        'poster': play['poster'],
                        'relateurl1': play['relateurl1'],
                    }
        
        # Convert the dictionary values back to a list
        similar_plays = list(similar_plays_dict.values())
        
        cursor.close()
        conn.close()
        return jsonify(similar_plays)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def format_selected_ids(selected_ids):
    if isinstance(selected_ids, str):
        # 문자열로 받은 경우, 쉼표로 분리
        ids = selected_ids.split(',')
    else:
        # 리스트로 받은 경우, 그대로 사용
        ids = selected_ids

    # 빈 문자열 제거 및 형식 수정
    formatted_ids = []
    current_id = ""
    for item in ids:
        if item.strip():  # 빈 문자열이 아닌 경우만 처리
            if item == 'P' or item == 'F':
                if current_id:
                    formatted_ids.append(current_id)
                current_id = "PF"
            else:
                current_id += item
    
    if current_id:
        formatted_ids.append(current_id)

    return formatted_ids


@app.route('/userinfo', methods=['POST'])
def getinfo():
    # 요청으로부터 JSON 데이터를 받습니다
    data = request.get_json()

    # 카카오 API에서 사용자 정보를 가져옵니다
    token_data = json.loads(data.get('tokenData', '{}'))
    access_token = token_data.get('access_token')
    
    if not access_token:
        return jsonify({"error": "Access token not provided"}), 400

    user_info = get_kakao_user_info(access_token)
    
    if not user_info:
        return jsonify({"error": "Failed to fetch user info from Kakao"}), 500

    # 사용자 정보를 데이터베이스에 저장합니다
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        insert_query = """
        INSERT INTO userinfo 
        (kakao_id, nickname, name, email, phone_number, birthday, gender, selected_ids, selected_area) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
        nickname = VALUES(nickname),
        name = VALUES(name),
        email = VALUES(email),
        phone_number = VALUES(phone_number),
        birthday = VALUES(birthday),
        gender = VALUES(gender),
        selected_ids = VALUES(selected_ids),
        selected_area = VALUES(selected_area)
        """
        selected_ids = data.get('selectedIds', [])
        formatted_selected_ids = format_selected_ids(selected_ids)
        selected_area = data.get('selectedArea', '')  # 클라이언트에서 전송한 selectedArea 값을 가져옵니다

        values = (
            user_info['id'],
            user_info['properties']['nickname'],
            user_info['kakao_account']['name'],
            user_info['kakao_account']['email'],
            user_info['kakao_account']['phone_number'],
            user_info['kakao_account']['birthday'],
            user_info['kakao_account']['gender'],
            ','.join(formatted_selected_ids),
            selected_area  # 새로 추가된 selectedArea 값
        )
        
        cursor.execute(insert_query, values)
        conn.commit()
        
        return jsonify({"message": "User info saved successfully"}), 200

    except mysql.connector.Error as err:
        conn.rollback()  # 에러 발생 시 롤백
        print(f"Database error: {err}")
        return jsonify({"error": "Database operation failed"}), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

            
def get_kakao_user_info(access_token):
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    response = requests.get("https://kapi.kakao.com/v2/user/me", headers=headers)
    if response.status_code == 200:
        return response.json()
    return None

if __name__ == '__main__':
    app.run(debug=True)