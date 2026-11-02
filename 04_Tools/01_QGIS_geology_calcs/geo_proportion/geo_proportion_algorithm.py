from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFileDestination,
    QgsProcessing,
)

from .geo_proportion_core import run_geo_proportion


class GeoProportionAlgorithm(QgsProcessingAlgorithm):
    """Processing algorithm wrapping the geological-proportion-by-sub-catchment
    calculation. Exposing this as a QgsProcessingAlgorithm (rather than only a
    dialog) gives users QGIS's built-in 'Run as Batch Process' dialog for
    processing many layer pairs in one go, plus command-line / scripted access
    via qgis_process or the Processing python API.
    """

    INPUT_GEO = 'INPUT_GEO'
    GEO_FIELD = 'GEO_FIELD'
    INPUT_CATCH = 'INPUT_CATCH'
    CATCH_FIELD = 'CATCH_FIELD'
    OUTPUT = 'OUTPUT'

    def tr(self, string):
        return QCoreApplication.translate('GeoProportionAlgorithm', string)

    def createInstance(self):
        return GeoProportionAlgorithm()

    def name(self):
        return 'geoproportionbysubcatchment'

    def displayName(self):
        return self.tr('Geological Proportion by Sub-Catchment')

    def group(self):
        return self.tr('Geological Tools')

    def groupId(self):
        return 'geologicaltools'

    def shortHelpString(self):
        return self.tr(
            'Intersects a geology polygon layer with sub-catchment polygons, '
            'calculates ellipsoidal areas, groups by geology type and '
            'sub-catchment ID, and writes a CSV summary with area (ha) and '
            'percentage columns.\n\n'
            'Use "Run as Batch Process" (right-click the algorithm) to '
            'process multiple geology/sub-catchment layer pairs in one go, '
            'each writing its own output CSV.'
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_GEO,
                self.tr('Geology layer'),
                [QgsProcessing.TypeVectorPolygon],
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.GEO_FIELD,
                self.tr('Geology type field'),
                parentLayerParameterName=self.INPUT_GEO,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_CATCH,
                self.tr('Sub-catchment layer'),
                [QgsProcessing.TypeVectorPolygon],
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.CATCH_FIELD,
                self.tr('Sub-catchment ID field'),
                parentLayerParameterName=self.INPUT_CATCH,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                self.tr('Output CSV'),
                fileFilter='CSV files (*.csv)',
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        geo_layer = self.parameterAsVectorLayer(parameters, self.INPUT_GEO, context)
        catch_layer = self.parameterAsVectorLayer(parameters, self.INPUT_CATCH, context)
        geo_field = self.parameterAsString(parameters, self.GEO_FIELD, context)
        catch_field = self.parameterAsString(parameters, self.CATCH_FIELD, context)
        output_csv = self.parameterAsFileOutput(parameters, self.OUTPUT, context)

        if geo_layer.id() == catch_layer.id():
            raise ValueError('The geology layer and sub-catchment layer must be different.')

        result = run_geo_proportion(
            geo_layer, catch_layer, geo_field, catch_field, output_csv,
            context=context, feedback=feedback,
        )

        feedback.pushInfo(
            f"{len(result['rows'])} rows written "
            f"({result['n_catchments']} sub-catchments x "
            f"~{result['n_geology_types']} geology types)."
        )

        return {self.OUTPUT: output_csv}
