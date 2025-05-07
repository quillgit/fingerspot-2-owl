import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="server.warroom",
        user="devuser",
        password="devuser",
        database="fin_pro"
    )