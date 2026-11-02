# -*- coding: utf-8 -*-
"""
/***************************************************************************
 SentinelOpenDialog

        begin                : 2023-08-19
        copyright            : (C) 2023 by FishFounder
        email                : fishfounderstartup@gmail.com
 ***************************************************************************/

"""

import os
from qgis.PyQt import uic, QtWidgets
from sentinelsat import SentinelAPI, read_geojson, geojson_to_wkt, make_path_filter
from datetime import date, timedelta
from qgis.core import QgsProject, QgsGeometry, QgsWkbTypes
from shapely.geometry import mapping
from shapely.ops import unary_union
from qgis.utils import iface
from qgis.PyQt.QtCore import QVariant
from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import QMainWindow, QFileDialog, QToolButton, QApplication
import subprocess
import sys
import ctypes
from osgeo import ogr, osr


import subprocess
import sys
import os
from qgis.PyQt import uic, QtWidgets
from datetime import date, timedelta
from qgis.core import QgsProject, QgsGeometry, QgsWkbTypes
from qgis.utils import iface
from qgis.PyQt.QtCore import QVariant
from PyQt5.QtCore import QDate
from qgis.core import QgsVectorLayer
from qgis.utils import iface
from tqdm import tqdm



# This loads your .ui file so that PyQt can populate your plugin with the elements from Qt Designer
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'sentinel_open_dialog_base.ui'))


class SentinelOpenDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(SentinelOpenDialog, self).__init__(parent)
        # Set up the user interface from Designer through FORM_CLASS.
        # After self.setupUi() you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)
        self.q1.setText(r'https://scihub.copernicus.eu/dhus')
        self.q2.textChanged.connect(self.login)
        self.q3.setEchoMode(QtWidgets.QLineEdit.Password)
        self.pb4.clicked.connect(self.handle_pb4_click)  # Użyj nowej metody
        self.pb4_clicked = False  # Flaga dla śledzenia kliknięcia pb4

        #zmienna globalna
        self.api = None



        #wybieraj z listy z mapy
        self.cblista.currentIndexChanged.connect(self.wybieraniewarstwzmapy)
        self.populateLayerComboBox()

        #flaga dla przycisku pobierz
        self.pb5.clicked.connect(self.handle_pb5_click)  # Użyj nowej metody
        self.pb5_clicked = False  # Flaga dla śledzenia kliknięcia pb5

        #self.q7.textChanged.connect(self.download)
        #self.q7.setText()
        self.q7.text()


        # Inicjalizacja interfejsu użytkownika, dodanie przycisku, itp.


        self.path.clicked.connect(self.choose_directory)
        self.path_1.clicked.connect(self.choose_directory_1)

        # Inicjalizacja zmiennej output_dir
        self.output_dir = ""

        self.logged_in = False

        # Dictionary mapping bands to filenames
        self.band_filenames = {
            'AOT_10m': ['AOT_10m.jp2'],
            'B02_10m': ['B02_10m.jp2'],
            'B03_10m': ['B03_10m.jp2'],
            'B04_10m': ['B04_10m.jp2'],
            'B08_10m': ['B08_10m.jp2'],
            'TCI_10m': ['TCI_10m.jp2'],
            'WVP_10m': ['WVP_10m.jp2'],
            'AOT_20m': ['AOT_20m.jp2'],
            'B01_20m': ['B01_20m.jp2'],
            'B02_20m': ['B02_20m.jp2'],
            'B03_20m': ['B03_20m.jp2'],
            'B04_20m': ['B04_20m.jp2'],
            'B05_20m': ['B05_20m.jp2'],
            'B06_20m': ['B06_20m.jp2'],
            'B07_20m': ['B07_20m.jp2'],
            'B8A_20m': ['B8A_20m.jp2'],
            'B11_20m': ['B11_20m.jp2'],
            'B12_20m': ['B12_20m.jp2'],
            'SCL_20m': ['SCL_20m.jp2'],
            'TCI_20m': ['TCI_20m.jp2'],
            'WVP_20m': ['WVP_20m.jp2']
        }


        self.down_active = False

        self.folder_opened = False
        self.process = None

        self.python.clicked.connect(self.open_python_window)  # Użyj nowej metody
        self.reload.clicked.connect(self.populateLayerComboBox)


        self.progress_bar.setValue(0)  # Ustaw wartość początkową na 0






    def open_python_window(self):

        # Otwórz konsolę Pythona w QGIS
        iface.actionShowPythonDialog().trigger()
        print("O kurczę, otwórz tę konsolę Pythona! Ta wtyczka Sentinel2 Solo Band jest jak mistrz kamuflażu wśród programów QGIS. Złap mnie, jeśli potrafisz!")
        print("Oh my goodness, open that Python console! The Sentinel2 Solo Band plugin is like a master of disguise among QGIS programs. Catch me if you can!")

    def choose_directory(self):
        dialog = QFileDialog(self)
        dialog.setFileMode(QFileDialog.Directory)

        selected_dir = dialog.getExistingDirectory(self)


        if selected_dir:
            self.output_dir = selected_dir.replace('/', '\\')
            self.q7.setText(self.output_dir)  # Ustawienie ścieżki jako tekst przycisku
            print("Selected directory:", self.output_dir)
            print("Wybrany katalog:", self.output_dir)




    # Dodaje wszystkie warstwy z mapy do listy
    def populateLayerComboBox(self):
        print("Adding all layers from the map to the list and opening the Python console")
        print('Dodaje wszystkie warstwy z mapy do listy i otworzenie konsoli python')
        # Clear the combobox
        self.cblista.clear()

        # Get a list of map layers from the QgsProject
        layers = QgsProject.instance().mapLayers().values()
        # Otwórz konsolę Pythona w QGIS
        #iface.actionShowPythonDialog().trigger()

        for layer in layers:
            if layer.source().lower().endswith('.shp') or layer.source().lower().endswith('.geojson'):
                self.cblista.addItem(layer.name())



#otwiera plik do shp



    def wybieraniewarstwzmapy(self, index):
        print("Selecting layers from the map")
        print('Wybieranie warstw z mapy')

        selected_layer_name = self.cblista.currentText()  # Get the name of the selected layer

        print(f'Selected layer: {selected_layer_name}')
        print(f'Wybrana warstwa: {selected_layer_name}')

        # Zakładam, że selected_layer_name zawiera pełną ścieżkę do pliku SHP





    def choose_directory_1(self):
        dialog = QFileDialog(self)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("Shapefiles (*.shp);;Pliki GeoJSON (*.geojson)")

        selected_file, _ = dialog.getOpenFileName(self)

        if selected_file:
            if selected_file.lower().endswith('.shp'):
                self.process_shp_to_geojson(selected_file)
            else:
                self.process_geojson(selected_file)



#konwersja SHP NA GEOJSON


    def process_shp_to_geojson(self, shp_path):
        shp_driver = ogr.GetDriverByName('ESRI Shapefile')
        shp_dataset = shp_driver.Open(shp_path)


        if shp_dataset:
            shp_layer = shp_dataset.GetLayer()
            shp_spatial_ref = shp_layer.GetSpatialRef()

            # Sprawdź, czy warstwa nie jest już w WGS84
            if shp_spatial_ref and shp_spatial_ref.GetAttrValue("AUTHORITY", 1) != "4326":
                wgs84_spatial_ref = osr.SpatialReference()
                wgs84_spatial_ref.ImportFromEPSG(4326)  # Kod EPSG dla WGS84
                coord_transform = osr.CoordinateTransformation(shp_spatial_ref, wgs84_spatial_ref)
            else:
                coord_transform = None

            geojson_driver = ogr.GetDriverByName('GeoJSON')

            index = 1
            while True:
                output_geojson_path = shp_path.replace('.shp', f'_{index}.geojson')
                if not os.path.exists(output_geojson_path):
                    break
                index += 1

            geojson_dataset = geojson_driver.CreateDataSource(output_geojson_path)
            geojson_layer = geojson_dataset.CreateLayer('', srs=wgs84_spatial_ref, geom_type=ogr.wkbPolygon)

            for feature in shp_layer:
                geom = feature.GetGeometryRef()
                if coord_transform:
                    geom.Transform(coord_transform)

                new_feature = ogr.Feature(geojson_layer.GetLayerDefn())
                new_feature.SetGeometry(geom.Clone())
                geojson_layer.CreateFeature(new_feature)
                new_feature = None

            geojson_dataset = None
            shp_dataset = None

            print("SHP file converted to GeoJSON:", output_geojson_path)
            QtWidgets.QMessageBox.warning(self, 'Attention', f'SHP file converted to GeoJSON: {output_geojson_path}')

            print("Plik SHP przekonwertowany na GeoJSON:", output_geojson_path)
            QtWidgets.QMessageBox.warning(self, 'Uwaga', f'Plik SHP przekonwertowany na GeoJSON: {output_geojson_path}')

            # output_geojson_path = "ścieżka/do/pliku.geojson"  # Zastąp to odpowiednią ścieżką
            #
            # message = f"SHP file converted to GeoJSON: {output_geojson_path}\n" \
            #           f"Plik SHP przekonwertowany na GeoJSON: {output_geojson_path}"
            #
            # message_box = QtWidgets.QMessageBox()
            # message_box.setWindowTitle('Attention / Uwaga')
            # message_box.setWindowIcon(
            #     QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxInformation))
            # message_box.setIcon(QtWidgets.QMessageBox.Information)
            # message_box.setText(message)
            # message_box.exec_()

            # Wczytaj nową warstwę GeoJSON do QGIS
            new_layer = QgsVectorLayer(output_geojson_path, f"New_GeoJSON_{index}", "ogr")

            if new_layer.isValid():
                QgsProject.instance().addMapLayer(new_layer)
                self.cblista.addItem(new_layer.name())  # Dodaj nową warstwę do comboboxa
                print("New layer added to QGIS:", new_layer.name())
                print("Nowa warstwa dodana do QGIS:", new_layer.name())
            else:
                print("Failed to load the new layer into QGIS.")
                print("Nie udało się wczytać nowej warstwy do QGIS.")

        else:
            print("Failed to open SHP file.")
            print("Nie udało się otworzyć pliku SHP.")



    # def process_geojson(self, geojson_path):
    #     # Wczytaj nową warstwę GeoJSON do QGIS
    #     new_layer = QgsVectorLayer(geojson_path, self.get_file_name(geojson_path), "ogr")
    #
    #     if new_layer.isValid():
    #         QgsProject.instance().addMapLayer(new_layer)
    #         self.cblista.addItem(new_layer.name())  # Dodaj nową warstwę do comboboxa
    #
    #
    #         # Display a message indicating the user needs to log in
    #         QtWidgets.QMessageBox.warning(self, 'Uwaga', f'Nowa warstwa GeoJSON dodana do QGIS: {new_layer.name()}')
    #
    #         print("Nowa warstwa GeoJSON dodana do QGIS:", new_layer.name())
    #     else:
    #         print("Nie udało się wczytać nowej warstwy GeoJSON do QGIS.")

    def process_geojson(self, geojson_path):
        if geojson_path.lower().endswith('.geojson'):
            # Extract the file name using os.path.basename
            file_name = os.path.basename(geojson_path)

            # Wczytaj nową warstwę GeoJSON do QGIS
            new_layer = QgsVectorLayer(geojson_path, file_name, "ogr")

            if new_layer.isValid():
                QgsProject.instance().addMapLayer(new_layer)
                self.cblista.addItem(new_layer.name())  # Dodaj nową warstwę do comboboxa

                # Wyświetl komunikat informujący, że warstwa GeoJSON została dodana
                QtWidgets.QMessageBox.warning(self, 'Attention', f'New GeoJSON layer added to QGIS: {new_layer.name()}')
                QtWidgets.QMessageBox.warning(self, 'Uwaga', f'Nowa warstwa GeoJSON dodana do QGIS: {new_layer.name()}')

                print("New GeoJSON layer added to QGIS:", new_layer.name())
                print("Nowa warstwa GeoJSON dodana do QGIS:", new_layer.name())
            else:
                print("Failed to load the new GeoJSON layer into QGIS.")
                print("Nie udało się wczytać nowej warstwy GeoJSON do QGIS.")
        else:
            print("The provided file is not in GeoJSON format. Please provide a file in *shp or GeoJSON format.")
            QtWidgets.QMessageBox.warning(self, 'Attention', 'The provided file is not in *shp or GeoJSON format. Please provide a file in GeoJSON format.')

            print("Podany plik nie jest w formacie *shp lub GeoJSON. Proszę podać plik w formacie GeoJSON.")
            QtWidgets.QMessageBox.warning(self, 'Uwaga', 'Podany plik nie jest w formacie *shp lub GeoJSON. Proszę podać plik w formacie GeoJSON.')



    def handle_pb4_click(self):
        self.pb4_clicked = True
        self.login()


    def login(self):
        #print('login(self)')
        value1 = self.q1.text()
        value2 = self.q2.text()
        value3 = self.q3.text()

        #if value1:
        if value1 and value2 and value3 and self.pb4_clicked:
            self.logged_in = True
            print(f'url: {value1}')
            print(f'Login: {value2}')
            print(f'Password: {value3}')


            self.api = SentinelAPI(value2, value3, value1)

            self.q4.setText("Connection successful. The plugin won't verify password compatibility if you've entered it incorrectly; it's best to restart the plugin. We don't collect login data. If you want to see login and image retrieval details, open a Python window in QGIS.")
            self.q44.setText("Połączenie udane. Wtyczka nie sprawdzi zgodności hasła, jeśli zostało wprowadzone nieprawidłowo; najlepiej jest zrestartować wtyczkę. Nie zbieramy danych logowania. Jeśli chcesz zobaczyć szczegóły logowania i pobierania obrazów, otwórz okno Pythona w QGIS.")

            # #Tworzenie komunikatu
            # message_box = QtWidgets.QMessageBox()
            # message_box.setWindowTitle('Login')
            # message_box.setIcon(QtWidgets.QMessageBox.Information)
            #
            # QtWidgets.QMessageBox.warning(self, 'Login', "Connection successful. The plugin won't verify password compatibility if you've entered it incorrectly; it's best to restart the plugin. We don't collect login data.")
            # QtWidgets.QMessageBox.warning(self, 'Logowanie', "Połączenie udane. Wtyczka nie będzie sprawdzać zgodności hasła, jeśli zostało wprowadzone nieprawidłowo; najlepiej jest zrestartować wtyczkę. Nie zbieramy danych logowania.")
            #
            # message_box.setStandardButtons(QtWidgets.QMessageBox.Ok)
            # message_box.exec_()

            # Tworzenie komunikatu
            message_box = QtWidgets.QMessageBox()
            message_box.setWindowTitle('Login')
            message_box.setWindowIcon(QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_ArrowRight))
            message_box.setIcon(QtWidgets.QMessageBox.Information)

            message_box.setText("Connection successful. The plugin won't verify password compatibility if you've entered it incorrectly; it's best to restart the plugin. We don't collect login data.")
            message_box.setInformativeText("Połączenie udane. Wtyczka nie będzie sprawdzać zgodności hasła, jeśli zostało wprowadzone nieprawidłowo; najlepiej jest zrestartować wtyczkę. Nie zbieramy danych logowania.")

            message_box.setStandardButtons(QtWidgets.QMessageBox.Ok)
            message_box.exec_()

            #self.api = SentinelAPI('fishfounder', 'LifeBelowWather1123', 'https://scihub.copernicus.eu/dhus')
            print('Login successful.')
            print('logowanie okej')


            ################################# Search and download ########################################






    def handle_pb5_click(self):
        print('Initiating preliminary satellite scene information retrieval.')
        print('Rozpoczynam wstepne pobieranie informacji o scenie satelitarnej')
        #self.pb5_clicked = True
        self.download()




    # def open_file(self, output_dir):
    #     try:
    #         if os.path.exists(output_dir):
    #             # Zamień ukośniki wsteczne na zwykłe ukośniki
    #             output_dir = output_dir.replace('/', '\\')
    #             print(f"Opening directory: {output_dir}")
    #             if sys.platform == 'win32':
    #                 subprocess.Popen(['explorer', output_dir], shell=True)
    #             elif sys.platform == 'darwin':
    #                 subprocess.Popen(['open', output_dir])
    #             else:
    #                 subprocess.Popen(['xdg-open', output_dir])
    #             print("Directory opened successfully.")
    #         else:
    #             print(f'Folder does not exist: {output_dir}')
    #     except Exception as e:
    #         print(f"An error occurred while opening the directory: {str(e)}")

    def open_file(self, output_dir):
        try:
            if os.path.exists(output_dir):
                # Sprawdź bieżący system operacyjny
                if sys.platform == 'win32':
                    # Zamień ukośniki wsteczne na zwykłe ukośniki na Windows
                    output_dir = output_dir.replace('/', '\\')
                    print(f"Opening directory: {output_dir}")
                    subprocess.Popen(['explorer', output_dir], shell=True)
                else:
                    # Pozostałe systemy operacyjne używają ukośników wstecznych
                    print(f"Opening directory: {output_dir}")
                    subprocess.Popen(['xdg-open', output_dir])
                print("Directory opened successfully.")
            else:
                print(f'Folder does not exist: {output_dir}')
        except Exception as e:
            print(f"An error occurred while opening the directory: {str(e)}")




    def download_band(self, s3, output_dir):

        n = 0
        total_files = len(s3)
        for x in s3:
            n += 1
            print('_2_: ' + str(n))

            progress = n / total_files * 100


            path_filter = make_path_filter("*{}".format(x))
            print(path_filter)

            print("Downloading spectral channels - {}".format(s3))
            print("Output path - {}".format(output_dir))
            print("Pobieranie kanałów spektralnych - {}".format(s3))
            print("Ścieżka zapisu - {}".format(output_dir))
            print('\n')
            print('\n')
            print("Rozpoczęto pobieranie. Proszę czekać, proces może potrwać chwilę.")
            print("Downloading has started. Please wait, the process may take a moment.")

            # Otwórz konsolę Pythona w QGIS
            # Sprawdź, czy konsola jest otwarta, i otwórz ją, jeśli nie
            # Otwórz konsolę Pythona w QGIS, jeśli jest zamknięta
            if not iface.actionShowPythonDialog().isVisible():
                iface.actionShowPythonDialog().trigger()

            self.api.download_all(self.products, directory_path=output_dir, nodefilter=path_filter)
            self.progress_bar.setValue(progress)

            print('\n')
            print("Download for - *{}".format(x))
            print("Pobieranie dla - *{}".format(x))
            self.Status_pobierania.setText("Download for *{}".format(x))



    # def download_band(self, s3, output_dir):
    #     print("Rozpoczęto pobieranie. Proszę czekać, proces może potrwać chwilę.")
    #     print("Downloading has started. Please wait, the process may take a moment.")
    #     n = 0
    #     total_files = len(s3)
    #     for x in s3:
    #         n += 1
    #         print('_2_: ' + str(n))
    #         path_filter = make_path_filter("*{}".format(x))
    #         print(path_filter)
    #
    #         print("Downloading spectral channels - {}".format(s3))
    #         print("Output path - {}".format(output_dir))
    #         print("Pobieranie kanałów spektralnych - {}".format(s3))
    #         print("Ścieżka zapisu - {}".format(output_dir))
    #
    #         Path_1 = r'{}'.format(output_dir)
    #         print(Path_1)
    #
    #         # Oblicz postęp na podstawie ilości pobranych plików
    #         progress = n / total_files * 100
    #         progress = n / total_files * 100
    #         self.progress_bar.setValue(progress)
    #         # Aktualizuj pasek postępu
    #         with tqdm(total=total_files, desc="Pobieranie pliku", initial=n, position=n) as progress_bar:
    #             # Tutaj będziesz używać rzeczywistych funkcji pobierania z biblioteki Sentinelsat
    #             self.api.download_all(self.products, directory_path=Path_1, nodefilter=path_filter)
    #             # Aktualizuj pasek postępu
    #             progress_bar.update(1)
    #
    #         print('\n')
    #         print("Download for - *{}".format(x))
    #         print("Pobieranie dla - *{}".format(x))
    #         self.Status_pobierania.setText("Download for - *{}".format(x))

    def download(self):
        print('Call the download function')
        print('Wywołaj funkcję pobierania')
        if not self.logged_in:
            # Display a message indicating the user needs to log in
            # QtWidgets.QMessageBox.warning(self, 'Attention', 'Log in before downloading.')
            # QtWidgets.QMessageBox.warning(self, 'Uwaga', 'Zaloguj się przed rozpoczęciem pobierania.')
            message = "Log in before downloading.\nZaloguj się przed rozpoczęciem pobierania."

            message_box = QtWidgets.QMessageBox()
            message_box.setWindowTitle('Attention / Uwaga')
            message_box.setWindowIcon(QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxWarning))
            message_box.setIcon(QtWidgets.QMessageBox.Warning)
            message_box.setText(message)
            message_box.exec_()

            return

        selected_layer_name = self.cblista.currentText()

        # if selected_layer_name not in QgsProject.instance().mapLayers():
        #     # Jeśli wybrana warstwa nie istnieje w projektach QGIS, wyświetl komunikat
        #     message = "The selected layer does not exist in the QGIS project.\nWybrana warstwa nie istnieje w projekcie QGIS."
        #
        #     message_box = QtWidgets.QMessageBox()
        #     message_box.setWindowTitle('Attention / Uwaga')
        #     message_box.setWindowIcon(
        #         QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxWarning))
        #     message_box.setIcon(QtWidgets.QMessageBox.Warning)
        #     message_box.setText(message)
        #     message_box.exec_()
        #
        #     return

        # Jeśli warstwa istnieje, kontynuuj z operacją pobierania
        layer = QgsProject.instance().mapLayersByName(selected_layer_name)[0]
        # selected_layer_name = self.cblista.currentText()
        # layer = QgsProject.instance().mapLayersByName(selected_layer_name)[0]


        # selected_layer_name = self.cblista.currentText()
        # layer = QgsProject.instance().mapLayersByName(selected_layer_name)[0]

        if layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            print('Only in GeoJSON format from map. The selected layer does not contain polygons. Choose a layer with polygons.')
            print("Tylko w formacie GeoJSON z mapy. Wybrana warstwa nie zawiera wielokątów. Wybierz warstwę zawierającą wielokąty.")

            QtWidgets.QMessageBox.warning(self, 'Attention', f'WARNING: Only in GeoJSON format from map. The selected layer does not contain polygons. Choose a layer with polygons. (not a GeoJSON file - you can load a *Shp file alongside)')
            QtWidgets.QMessageBox.warning(self, 'Uwaga',  f'OSTRZEŻENIE: Tylko w formacie GeoJSON z mapy. Wybrana warstwa nie zawiera wielokątów. Wybierz warstwę zawierającą wielokąty. (nie jest to plik GeoJSON - możesz załadować plik *Shp obok)')

            return

        if layer.featureCount() == 0:

            print('Only in GeoJSON format from map')
            print('Tylko w formacie GeoJSON z mapy')
            QtWidgets.QMessageBox.warning(self, 'Attention', f'WARNING: Only in GeoJSON format from map. The selected layer does not contain polygons. Choose a layer with polygons. (not a GeoJSON file - you can load a *Shp file alongside)')
            QtWidgets.QMessageBox.warning(self, 'Uwaga', f'OSTRZEŻENIE: Tylko w formacie GeoJSON z mapy. Wybrana warstwa nie zawiera wielokątów. Wybierz warstwę zawierającą wielokąty. (nie jest to plik GeoJSON - możesz załadować plik *Shp obok)')

            return

        feature = next(layer.getFeatures())
        footprint_wkt = feature.geometry().asWkt()




        # # Definicja przedziału dat
        # # start_date = date.today() - timedelta(days=5)
        start_date = self.da1.date().toPyDate()
        # # end_date = date.today()
        end_date = self.da2.date().toPyDate()

        # # Wyszukaj produkty Sentinel-2 odpowiadające zdefiniowanym kryteriom
        products_0 = self.api.query(footprint_wkt,
                               date=(start_date, end_date),
                               platformname='Sentinel-2',
                               producttype='S2MSI2A',
                               cloudcoverpercentage=(0, self.cloud.value()))

        # Pobranie listy identyfikatorów produktów z kluczy słownika products_0
        identyfikatory_produktow = list(products_0.keys())


        print(identyfikatory_produktow)
        print(len(identyfikatory_produktow))
        # Changing the message:

        # QtWidgets.QMessageBox.warning(self, 'Attention', f'WARNING: {len(identyfikatory_produktow)} satellite scene(s) have been located for the selected spectral band.')
        # QtWidgets.QMessageBox.warning(self, 'Uwaga', f'OSTRZEŻENIE: Znaleziono {len(identyfikatory_produktow)} scen(y) satelitarne dla wybranego pasma spektralnego.')
        #num_scenes = len(identyfikatory_produktow)
        num_scenes = len(identyfikatory_produktow)
        message = f"WARNING: {num_scenes} satellite scene(s) have been located for the selected spectral band.\n" \
                  f"OSTRZEŻENIE: Znaleziono {num_scenes} scen(y) satelitarne dla wybranego pasma spektralnego.\n" \
                  f"AVERTISSEMENT : {num_scenes} scène(s) satellite(s) ont été localisée(s) pour la bande spectrale sélectionnée."

        message_box = QtWidgets.QMessageBox()
        message_box.setWindowTitle('Attention / Uwaga / Avertissement')
        message_box.setWindowIcon(
            QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxWarning))
        message_box.setIcon(QtWidgets.QMessageBox.Warning)
        message_box.setText(message)
        message_box.exec_()

        # Iteracja przez wszystkie produkty w products_0
        z = 0
        for identyfikator_produktu in identyfikatory_produktow:
            informacje_o_produkcie = products_0[identyfikator_produktu]


            # to jest po to żeby sprawdzić czy foto jest offline czy online
            product_info = self.api.get_product_odata(identyfikator_produktu)

            #print(product_info)
            is_online = product_info['Online']
            print("Connection status is: " + str(is_online) + ", please open the Python console in QGIS to learn more.")
            print("Status połączenia to: " + str(is_online) + ", proszę otworzyć konsolę Pythona w QGIS, aby dowiedzieć się więcej.")

            #z += 1
            #print('Przejście - for nr 1: ' + str(z))
            if is_online:
                # Wydobycie potrzebnych informacji o produkcie

                # Wydobycie potrzebnych informacji o produkcie
                print('\n')
                print('\n')
                print('\n')
                print("Now I will be downloading: " + informacje_o_produkcie['title'])
                print('Teraz będę pobierać: ' + informacje_o_produkcie['title'])
                # QtWidgets.QMessageBox.warning(self, 'Attention', "Now I will download. Please click 'OK' and wait for the program to start downloading the image. Even if there's no immediate response, please wait patiently.")
                # QtWidgets.QMessageBox.warning(self, 'Uwaga', "Teraz rozpocznę pobieranie. Proszę kliknąć 'OK' i czekać, aż program rozpocznie pobieranie obrazu. Nawet jeśli nie ma natychmiastowej odpowiedzi, proszę cierpliwie czekać.")

                message = "Now I will download. Please click 'OK' and wait for the program to start downloading the image. Even if there's no immediate response, please wait patiently."
                message_pl = "Teraz rozpocznę pobieranie. Proszę kliknąć 'OK' i czekać, aż program rozpocznie pobieranie obrazu. Nawet jeśli nie ma natychmiastowej odpowiedzi, proszę cierpliwie czekać."

                messageBox = QtWidgets.QMessageBox()
                messageBox.setIcon(QtWidgets.QMessageBox.Warning)
                messageBox.setWindowTitle('Attention / Uwaga')
                messageBox.setText(message)
                messageBox.setInformativeText(message_pl)
                messageBox.addButton(QtWidgets.QMessageBox.Ok)
                messageBox.exec_()

                # Pobranie produktów na podstawie informacji o produkcie
                self.products = self.api.query(footprint_wkt,
                                               date=(start_date, end_date),
                                               platformname='Sentinel-2',
                                               producttype='S2MSI2A',
                                               cloudcoverpercentage=(0, self.cloud.value()),
                                               filename='{}'.format(informacje_o_produkcie['filename']))

                ###################### 10m ##############################
                if self.ALL_10m.isChecked():

                    s3 = ['AOT_10m.jp2', 'B02_10m.jp2', 'B03_10m.jp2', 'B04_10m.jp2', 'B08_10m.jp2', 'TCI_10m.jp2', 'WVP_10m.jp2']

                    print('ALL_10m')

                ###################### 20m ##############################
                elif self.ALL_20m.isChecked():
                    s3 = ['AOT_20m.jp2', 'B01_20m.jp2', 'B02_20m.jp2', 'B03_20m.jp2', 'B04_20m.jp2', 'B05_20m.jp2', 'B06_20m.jp2', 'B07_20m.jp2', 'B8A_20m.jp2', 'B11_20m.jp2', 'B12_20m.jp2', 'SCL_20m.jp2', 'TCI_20m.jp2', 'WVP_20m.jp2']
                    print('ALL_20m')

                ###################### ELSE ##############################
                else:
                    selected_bands = [band for band in self.band_filenames if getattr(self, band).isChecked()]
                    print('Band: '+str(selected_bands))



                    if not selected_bands:
                        print('No channels selected for download.')
                        print('Nie wybrano żadnych kanałów do pobrania.')
                        # QtWidgets.QMessageBox.warning(self, 'Attention', 'The band for download has not been selected.')
                        # QtWidgets.QMessageBox.warning(self, 'Attention', 'The band for download have not been selected.')
                        message = "The band for download has not been selected."
                        message_pl = "Nie wybrano pasma do pobrania."

                        messageBox = QtWidgets.QMessageBox()
                        messageBox.setIcon(QtWidgets.QMessageBox.Warning)
                        messageBox.setWindowTitle('Attention / Uwaga')
                        messageBox.setText(message)
                        messageBox.setInformativeText(message_pl)
                        messageBox.addButton(QtWidgets.QMessageBox.Ok)
                        messageBox.exec_()

                        return


                    s3 = []
                    for band in selected_bands:
                        s3.extend(self.band_filenames.get(band, []))
                        print(s3[:])




                if not s3:
                    print('No files to download.')
                    print('Brak plików do pobrania.')
                    return

                print(s3[:])

                output_dir = self.q7.text()
                print(output_dir)

####################### OPEN ################################
                if self.OPEN.isChecked():
                    self.open_file(output_dir)
#######################################################

                print('xd')
                print(f"s3: {s3}")
                print(f"output_dir: {output_dir}")
                self.download_band(s3, output_dir)


            else:
                # QtWidgets.QMessageBox.warning(self, 'Attention','The scene is offline or no scenes were found to download')
                message = "The scene is offline or no scenes were found to download."
                message_pl = "Scena jest niedostępna lub nie znaleziono scen do pobrania."

                messageBox = QtWidgets.QMessageBox()
                messageBox.setIcon(QtWidgets.QMessageBox.Warning)
                messageBox.setWindowTitle('Attention / Uwaga')
                messageBox.setText(message)
                messageBox.setInformativeText(message_pl)
                messageBox.addButton(QtWidgets.QMessageBox.Ok)
                messageBox.exec_()

            # Resetowanie listy s3 dla kolejnego produktu
            s3 = []





