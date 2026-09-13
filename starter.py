from app.main import bootstrap
import app.extensions  # registers enrollment/build routes before startup

if __name__ == '__main__':
    bootstrap()
