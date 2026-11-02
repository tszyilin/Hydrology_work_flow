from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .geo_proportion_algorithm import GeoProportionAlgorithm


class GeoProportionProvider(QgsProcessingProvider):

    def id(self):
        return 'geoproportion'

    def name(self):
        return 'Geological Proportion'

    def icon(self):
        return QIcon(':/images/themes/default/mIconPolygonLayer.svg')

    def loadAlgorithms(self):
        self.addAlgorithm(GeoProportionAlgorithm())
