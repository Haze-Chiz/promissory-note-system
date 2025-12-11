from app import app, db
from models import ActiveSettings

with app.app_context():
    ActiveSettings.__table__.drop(db.engine)
    print("ActiveSettings table dropped successfully.")
