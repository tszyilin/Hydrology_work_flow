import subprocess
import os

def install_dependencies():
    try:
        subprocess.check_call(['pip', 'install', '-r', 'requirements.txt'])
        print("Wymagane biblioteki zostały pomyślnie zainstalowane.")
    except Exception as e:
        print(f"Błąd podczas instalacji bibliotek: {e}")

if __name__ == "__main__":
    # Sprawdź, czy istnieje plik 'install_deps.py' i czy nie został już zainstalowany
    if os.path.isfile('install_deps.py'):
        print('Ostrzeżenie: Nowe zależności zostaną teraz zainstalowane...')
        install_dependencies()
        os.rename('install_deps.py', 'install_deps.installed')
    else:
        print('Plik "install_deps.py" nie istnieje lub został już zainstalowany. Nie wykonano żadnych operacji.')
