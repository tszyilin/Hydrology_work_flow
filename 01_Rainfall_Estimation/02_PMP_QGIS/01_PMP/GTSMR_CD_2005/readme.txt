                     Bureau of Meteorology
                          Australia
------------------------------------------------------------------
        GENERALISED TROPICAL STORM METHOD-REVISED VERSION       
------------------------------------------------------------------
          
             Copyright Bureau of Meteorology 2003
                  Version 1 - March 2004
	          Reissued September 2005

This CD contains the method and data required to derive and apply
estimates of PMP for the areas of Australia affected by storms of 
tropical origin. 


--------------
File Directory
--------------
-Copyright Notice
-Disclaimer
-CD Directory 
       (1) readme.txt
       (2) documents/
       (3) pmp_zones/
       (4) depth_area_data/
       (5) gridded_data/
       (6) temporal_patterns/
       (7) worked_examples/
	

----------------
COPYRIGHT NOTICE
----------------
Copyright in this material resides with the Commonwealth of 
Australia,however the sponsoring agencies are granted a 
non-exclusive, non-transferable, royalty-free licence to use 
same in connection with present and future works. The material 
must not be distributed without this copyright notice and the 
disclaimer below.


----------
DISCLAIMER                        
----------
'Guidebook to the Estimation of Probable Maximum Precipitation:
GENERALISED TROPICAL STORM METHOD (GTSMR)' offers guidance to
those engaged in estimating the probable maximum precipitation 
for durations up to one hundred and twenty hours in regions of 
Australia affected by tropical storms. The 'Guidebook to the 
Estimation of Probable Maximum Precipitation:GENERALISED 
TROPICAL STORM METHOD (GTSMR)' has been prepared by the Bureau 
of Meteorology as part of the Generalised Tropical Storm Method 
(GTSM) Revision Project. Despite careful preparation, it may 
contain typographical or other errors that affect use of the 
procedures and/or the numerical values obtained. Readers are 
encouraged to report suspected errors to the Hydrology Unit of 
the Bureau of Meteorology. Once confirmed, errors will be noted 
and, where circumstances allow, corrected. The Bureau of 
Meteorology will use all reasonable endeavours to communicate 
errors, whether suspected or confirmed, through the 
Hydrometeorological Advisory Service section of the Bureau web 
site: http://www.bom.gov.au/hydro/has/.  The Bureau of 
Meteorology does not accept liability for losses arising from 
use of the GTSMR, or its procedures, howsoever caused and has 
not approved any instruction that use of the GTSMR procedures 
be made mandatory for particular applications. This publication
is a guide only and is made available on the understanding that 
the Bureau is not thereby engaged in rendering professional 
services or advice. Users of the guidebook take full 
responsibility for the quality of the estimates of probable 
maximum precipitation resulting from application of the 
guidance provided.


------------
CD Directory
------------
	
(1)readme.txt


(2)documents/

   2.1 gtsmr_guidebook_2005.pdf     ***go here next***

   'Guidebook to the Estimation of Probable Maximum
   Precipitation: GENERALISED TROPICAL STORM METHOD' book in
   format readable by Adobe Acrobat Reader. This document 
   explains how all the other files on this CD are used.
   The 2005 re-issue has some corrections to the example      catchment B workings.
     
   2.2 gtsmr_hrs8.pdf
  
   'Revision of the Generalised Tropical Storm Method for
   Estimating Probable Maximum Precipitation', Hydrology
   Report Series No.8, known as HRS8. This report gives the
   developmental and theoretical background to the method of PMP
   estimation described in the Guidebook.

   2.3 gtsmr_hrs9.pdf

   'Catalogue of Significant Rainfall Occurrences of Tropical
   Origin over Australia', Hydrology Report Series No.9, known
   as HRS9. This report catalogues the characteristics of the
   122 storms used in deriving the GTSMR. 
   
   2.4 method_zones.pdf

   Figure 1.1 in a format readable by Adobe Acrobat Reader and
   at a scale appropriate for printing on A3 paper. It provides
   details such as river basin outlines and graticules at 1°
   spacing that are not included in the figure in the Guidebook.

   2.5 worksheet_1.pdf
   2.6 worksheet_2.pdf

   Worksheets given in Appendix A in a format readable by
   Adobe Acrobat Reader at a scale appropriate for printing on
   A4 paper.

   2.7 gtsmr_worksheet_1.doc
   2.8 gtsmr_worksheet_2.doc
   2.9 gsdm_calculation_sheet.doc

   Worksheets given in Appendix A in Microsoft Word format for 
   easy insertion into reports. The calculation sheet for the 
   Generalised Short-Duration Method is also included.


(3)pmp_zones/
   
   3.1 zones_all.shp
   3.2 zones_all.shx
   3.3 zones_all.dbf

   These files make up a shapefile of the PMP application zones 
   over Australia and are suitable for viewing using GIS    software. 


(4)depth_area_data/

   4.1 coastal_summer.xls
   4.2 inland_summer.xls
   4.3 swwa_winter.xls

   The depth_area datafiles are in Excel format and are a table
   of rainfall depths in mm for areas in km² at increasing
   intervals for each of the standard durations.

   Sample:
   INLAND SUMMER					
               DEPTH(mm) DEPTH(mm) DEPTH(mm) DEPTH(mm) DEPTH(mm)
   AREA(km²)    24h       36h       48h       72h       96h
     1        1010.000  1188.000  1353.000  1645.000  1860.000
     1.5      1005.950  1181.485  1344.195  1632.321  1844.152
     2        1003.076  1176.862  1337.949  1623.326  1832.907
     2.5      1000.847  1173.276  1333.103  1616.348  1824.185
      |           |         |         |         |         |
   120000      418.330   463.368   503.232   578.722   646.101
   130000      408.174   452.163   490.943   564.568   631.355
   140000      398.636   441.686   479.430   551.349   617.687
   150000      390.000   432.000   468.000   539.000   605.000

   4.4 coastal_summer.pdf
   4.5 inland_summer.pdf
   4.6 swwa_winter.pdf

   Depth_area curves in a format readable by Adobe Acrobat Reader
   and at a scale appropriate for printing on A3 paper.


(5)gridded data/
   
   5.1 taf.asc.zip          Topographic Adjustment factor
   5.2 daf.asc.zip          Decay Amplitude Factor      
   5.3 epw_annual.asc.zip   Equivalent Precipitable Water-annual
   5.4 epw_winter.asc.zip   Equivalent Precipitable Water-winter

   Catchment adjustment factor grids. 
   These factors are provided as regular grids of point values
   compressed using WinZip 8.0. Please note that these files are
   large; their approximate sizes being-

                Zipped (Bytes)      Unzipped (Bytes)
   _________________________________________________
   epw_annual      92,375,772         472,550,790
   epw_winter      93,764,374         472,530,300
   taf             36,254,069         376,947,398               
   daf             37,985,566         410,275,573



   i.   The extent of each grid is   9.99°S to  44.01°S
                                   109.99°E to 158.01°E

   ii.  The spacing of each grid is 0.005°

   iii. Grid points with no value (eg. over the sea) are coded as
        -9999. 

   iv.  When 'unzipped' the files have the titles
        taf.asc
        daf.asc
        epw_annual.asc
        epw_winter.asc
        
   v.   The structure of the grids is-
	a. The first 6 rows give information about the grid set
           up as required by Arcview.
        b. Grid values are in free format.
        c. The following rows contain the value at each grid
           point across the 9605 points lying between 109.990°E
           and 158.010°E inclusive at 0.005° intervals. The 6805
           rows cover the latitudes between 9.990°S to 44.01°S
           inclusive at 0.005° intervals. 


         ncols         9605
         nrows         6805
         xllcorner     109.9875
         yllcorner     -44.0125
         cellsize      0.005
         NODATA_value  -9999
         -9999 -9999 -9999 -9999 -9999 -9999 -9999  and so on
         -9999 -9999 -9999 -9999 -9999 -9999 -9999      "
         -9999 -9999 -9999 -9999 -9999 -9999 -9999      " 
         -9999 -9999 -9999 -9999 -9999 -9999 -9999      " 
         -9999 -9999 -9999 -9999 -9999 -9999 -9999      "
         -9999 -9999 -9999 -9999 -9999 -9999 -9999      "
         -9999 -9999 -9999 -9999 -9999 -9999 -9999      " 
         -9999 -9999 -9999 -9999 -9999 -9999 -9999      " 
         -9999 -9999 -9999 -9999 -9999 -9999 -9999      " 
            " and so on 
  

(6)temporal_patterns/

   6.1 standard_area_100/
     6.1.1 coastal_avm_100.xls
     6.1.2 coastal_storms_100.xls
     6.1.3 inland_avm_100.xls
     6.1.4 inland_storms_100.xls
     6.1.5 swwa_storms_100.xls

     and so on for all standard areas to
   
   6.11 standard_area_150000/
     6.11.1 coastal_avm_150000.xls
     6.11.2 coastal_storms_150000.xls
     6.11.3 inland_avm_150000.xls
     6.11.4 inland_storms_150000.xls
     6.11.5 swwa_storms_150000.xls

   The temporal pattern files are in Excel format and they are    fully listed in Appendix B of Guidebook 


     Standard Areas:           Standard Durations:
           100 km²                      24 hours
           500 km²                      36 hours
         1,000 km²                      48 hours
         2,500 km²                      72 hours
         5,000 km²                      96 hours
        10,000 km²                     120 hours (coastal only)
        20,000 km²
        40,000 km²
        60,000 km²
       100,000 km²
       150,000 km²

    Pattern Types:
      Coastal AVM Design Pattern             coastal_avm_XXX.xls
      Inland AVM Design Pattern               inland_avm_XXX.xls
      Coastal Storm Patterns(biggest 10)  coastal_storms_XXX.xls
      Inland Storm Patterns (biggest 10)   inland_storms_XXX.xls
      SWWA Storm Pattern                     swwa_storms_XXX.xls	

    Pattern Type Explanations:
       i. 'AVM' refers to the temporal patterns generated using 
          the Average Variability Method.
      ii. 'swwa' is the southwest Western Australia zone
     iii. 'Storm' Pattern refers to the individual storm
          patterns for that zone.
      iv. 'XXX' stands for the relevant standard area.
       v. No AVM design patterns are available for the SWWA zone.
       
    Key to Temporal Pattern Headings
     Time_hrs (all files):
       The time elapsed from the start of the standard burst
       duration to its end, in intervals of 3 hours. 

     Time_% (all files):
       The elapsed time expressed as a percentage of the standard
       Burst duration.

     Incremental_% (AVM files):
       The percentage of the total rainfall depth that fell in the 
       preceding 3 hourly segment of the standard burst duration 
       as derived using the AVM on the 10 biggest observed storms.

     Cumulative_% (AVM files):
       The percentage of the total rainfall depth that fell up to
       that time within the standard burst duration as derived
       using the AVM on the 10 biggest observed storms.

     YYYYMONDD-D (Storm files):
       The title is an identifier showing the year,month,end date 
       and duration of the particular storm, in that order. The 
       storm is one of the, up to 10, biggest observed at that 
       standard area and duration.
       The figures are the incremental percentages for the storm 
       i.e. the percentage of the total rainfall depth which fell 
       in the preceding 3hourly segment of the standard burst 
       duration for the storm.
        

    Sample:  coastal_avm_1000.xls
 
     24HOURS			
     Time_hrs Time_% Incremental_% Cumulative_%
       3       12.5     10.96        10.96
       6       25       14.15        25.11
       9       37.5     12.49        37.60
      12       50       23.97        61.57
      15       62.5     17.39        78.96
      18       75        7.10        86.06
      21       87.5      8.65        94.71
      24      100        5.29       100.00
     36HOURS and so on up to 120 hours.


(7) worked_examples/
 
  7.1 test_catch_a_nsw.dbf
  7.2 test_catch_a_nsw.shp
  7.3 test_catch_a_nsw.shx

  7.4 test_catch_b_wa.dbf
  7.5 test_catch_b_wa.shp
  7.6 test_catch_b_wa.shx

  These are shapefiles for two hypothetical catchments suitable 
  for viewing using GIS software. They are for use in working
  through the examples of applying the GTSMR given in Section 5
  of the Guidebook. 



