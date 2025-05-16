import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="server.warroom",
        user="devuser",
        password="devuser",
        database="fin_pro"
    )

def get_owl_connection():
    return mysql.connector.connect(
        host="erp.mktr.co.id",
        user="agung",
        password="your_password",
        database="owl"
    )