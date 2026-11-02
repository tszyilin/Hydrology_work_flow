                     Bureau of Meteorology
                          Australia
------------------------------------------------------------------
           GENERALISED SOUTHEAST AUSTRALIA METHOD
------------------------------------------------------------------
          
             Copyright Bureau of Meteorology 2006
                  Version 1 - October 2006

This CD contains the method and data required to derive and apply
estimates of PMP in areas of south eastern Australia not affected
by storms of tropical origin or in regions where such storms are
unlikely to cause the extreme rainfall event.

Cover image: Storm over Wheatfield, Dimboola, Victoria
             (c)copyright Keith Carroll (www.keithcarroll.id.au)
------------------------------------------------------------------
File Directory
------------------------------------------------------------------
-Copyright Notice
-Disclaimer
-CD Directory 
       (1) readme.txt
       (2) documents/
       (3) pmp_zones/
       (4) depth_area_data/
       (5) gridded_data/
       (6) temporal_distributions/
       (7) worked_examples/	

------------------------------------------------------------------
COPYRIGHT NOTICE
------------------------------------------------------------------
Copyright in this material resides with the Commonwealth of 
Australia. The material must not be distributed without this 
copyright notice and the disclaimer below.


------------------------------------------------------------------
DISCLAIMER                        
------------------------------------------------------------------
'Guide to the Estimation of Probable Maximum Precipitation:
GENERALISED SOUTHEAST AUSTRALIA METHOD(GSAM)' offers guidance to
those engaged in estimating the probable maximum precipitation for
durations up to ninety six hours in regions of Australia not
affected by tropical storms or in regions where such storms are
unlikely to cause the extreme rainfall event. The 'Guide to the 
Estimation of Probable Maximum Precipitation: GENERALISED 
SOUTHEAST AUSTRALIA METHOD (GSAM)' has been prepared by the Bureau
of Meteorology with the greatest care.  However, it may contain
typographical or other errors that affect use of the procedures 
and/or the numerical values obtained. Readers are encouraged to 
report suspected errors to the Hydrology Unit of the Bureau of 
Meteorology. Once confirmed, errors will be noted and, where 
circumstances allow, corrected. The Bureau of Meteorology will use
all reasonable endeavours to communicate errors, whether suspected
or confirmed, through the Hydrometeorological Advisory Service 
section of the Bureau web site: http://www.bom.gov.au/hydro/has/.
The Bureau of Meteorology does not accept liability for losses 
arising from use of the GSAM, or its procedures, howsoever caused 
and has not approved any instruction that use of the GSAM 
procedures be made mandatory for particular applications. This 
publication is a guide only and is made available on the 
understanding that the Bureau is not thereby engaged in rendering 
professional services or advice.  Users of the guidebook take full
responsibility for the quality of the estimates of probable 
maximum precipitation resulting from application of the guidance 
provided.


------------------------------------------------------------------
CD Directory
------------------------------------------------------------------
(1)readme.txt


(2)documents/

   2.1 gsam_guidebook.pdf     ***read this guidebook first***

   'GUIDEBOOK TO THE ESTIMATION OF PROBABLE MAXIMUM PRECIPITATION:
   GENERALISED SOUTHEAST AUSTRALIA METHOD' book in PDF format,
   readable by Adobe Acrobat Reader. This document explains how
   all the other files on this CD are used.
   
   2.2 gsam_hrs4.pdf
  
   'Development of the Generalised Southeast Australia Method for
   Estimating Probable Maximum Precipitation'(August, 1996), 
   Hydrology Report Series No.4, known as HRS4. This report gives
   the developmental and theoretical background to the method of
   PMP estimation described in the Guidebook.

   2.3 gsam_hrs3.pdf

   'Catalogue of Significant Rainfall Occurrences over Southeast
   Australia'(October 1995), Hydrology Report Series No.3, known
   as HRS3. This report catalogues the characteristics of the
   110 storms used in deriving the GSAM. This version is as
   reprinted in May 2005.
   
   2.4 gsdm_manual.pdf

   'The Estimation of Probable Maximum Precipitation in Australia:
   Generalised Short-Duration Method'(June 2003). A guide to the
   background and application of the GSDM to be used in conjuction
   with the GSAM Guide for catchments smaller than 1000km².

   2.5 method_zones.pdf

   Figure 1.1 of the Guidebook in a format readable by Adobe 
   Acrobat Reader and at a scale appropriate for printing on A3 
   paper. It provides details such as river basin outlines and 
   graticules at 1°spacing that are not included in the figure in 
   the Guidebook version.

   2.6  gsam_worksheet_1.pdf
   2.7  gsam_worksheet_2.pdf
   2.8  gsdm_worksheet.pdf

   Worksheets given in Appendix A in a format readable by
   Adobe Acrobat Reader at a scale appropriate for printing on
   A4 paper. The calculation sheet for the Generalised Short-
   Duration Method is also included.

   2.9  gsam_worksheet_1.doc
   2.10 gsam_worksheet_2.doc
   2.11 gsdm_worksheet.doc

   Worksheets given in Appendix A in Microsoft Word format for 
   easy insertion into reports. 


(3)pmp_zones/
   
   3.1 pmp_zones.shp
   3.2 pmp_zones.shx
   3.3 pmp_zones.dbf
   3.4 pmp_zones.prj

   These files make up a shapefile of the PMP application zones 
   over Australia and are suitable for viewing using GIS software.

   3.5 gsdm_limits.shp
   3.6 gsdm_limits.shx
   3.7 gsdm_limits.dbf
   3.8 gsdm_limits.prj

   These files make up a shapefile of the duration limits of the 
   Generalised Short-Duration Method suitable for viewing using 
   GIS software.

(4)depth_area_data/

   4.1 gsam_coastal_autumn.xls
   4.2 gsam_coastal_summer.xls
   4.3 gsam_inland_autumn.xls
   4.4 gsam_coastal_summer.xls

   The depth_area datafiles are in Excel format and are a table
   of rainfall depths in mm for areas in km² at increasing
   intervals for each of the standard durations.

   Sample:
   INLAND SUMMER
             DEPTH(mm)  DEPTH(mm)  DEPTH(mm)  DEPTH(mm)  DEPTH(mm)
   AREA(km2)  24h        36h        48h        72h        96h
     1       498.138    533.000    558.995    604.861    620.380
    1.5      495.201    529.720    555.016    600.581    617.211
     2       493.017    527.266    552.056    597.418    614.840
    2.5      491.266    525.297    549.693    594.903    612.936
      |         |          |          |          |          |  
    85000    244.179    271.858    280.608    284.760    303.520
    90000    241.307    268.754    277.597    282.019    299.809
    95000    238.585    265.805    274.732    279.438    296.309
   100000    236.000    263.000    272.000    277.000    293.000

   4.5 gsam_coastal_autumn.pdf
   4.6 gsam_coastal_summer.pdf
   4.7 gsam_inland_autumn.pdf
   4.8 gsam_inland_summer.pdf

   Depth_area curves in a format readable by Adobe Acrobat Reader
   and at a scale appropriate for printing on A3 paper.

   4.9 gsdm_depth_area.pdf

   Generalised Short-Duration Method depth_area curves in a format
   readable by Adobe Acrobat Reader and at a scale appropriate for
   printing on A3 paper.


(5)gridded data/
   
   5.1 gsam_taf.asc.zip     Topographic Adjustment factor in GSAM 
                            application zone
   5.2 epw_annual.asc.zip   Equivalent Precipitable Water-annual
                                                         (summer)
   5.3 epw_autumn.asc.zip   Equivalent Precipitable Water-autumn

   Catchment adjustment factor grids. 
   These factors are provided as regular grids of point values
   that have been compressed (zipped)within MS Windows. Please 
   note that these files are large; their approximate sizes being-

                Zipped (KB)      Unzipped (KB)
   _________________________________________________
   epw_annual    92,376           472,551
   epw_autumn    93,312           472,548
   gsam_taf      13,748           156,681


   (i)  The extents of the grids are-
        epw grids        9.99°S to 44.01°S  /109.99°E to 158.01°E
        gdam_taf grid   26.51°S to 44.005°S /117.99°E to 154.00°E

   (ii) The spacing of each grid is 0.005°

   (iii)Grid points with no value (e.g. over the sea) are coded as
        -9999. 

   (iv) When 'unzipped' the files have the titles
        gsam_taf.asc
        epw_annual.asc
        epw_autumn.asc
        
   (v)  The structure of the grids is-
        a. The first 6 rows give information about the grid setup
           as required by a GIS (e.g. ArcMap).
        b. Grid values are in free format.
        c. For the epw grids, the following rows contain the value 
           at each grid point across the 9605 points lying between
           109.990°E and 158.010°E inclusive at 0.005° intervals. 
           The 6805 rows cover the latitudes between 9.990°S to 
           44.010°S inclusive at 0.005° intervals.
           Similarly, for the gsam_taf grid, the following rows 
           contain the value at each grid point across the 7203 
           points lying between 117.99°E to 154.00°E inclusive at 
           0.005° intervals and the 3500 rows cover the latitudes 
           between 26.51°S to 44.005°S inclusive at 0.005° 
           intervals.  
        d. The xllcorner and yllcorner values define the lower
           left corner of the display of the raster created from 
           the .asc file, not the grid itself; they are half a 
           grid-spacing (0.0025°) offset to the south-west of the 
           south-west extent of the grid.


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


(6)temporal_distributions/

   6.1 standard_area_100/
     6.1.1 coastal_100.xls
     6.1.2 inland_100.xls
         .
         and so on for all standard areas to 40,000 km²
         .  
   6.8 standard_area_40000/
     6.8.1 coastal_40000.xls
     6.8.2 coastal_40000.xls

   6.9 pre_burst_temporal distributions/
     6.9.1 pre_burst_coastal.xls
     6.9.2 pre_burst_inland.xls

     The design temporal distribution of PMP and pre-burst 
     distribution files are in MS Excel format and they are 
     fully listed in Appendix B of the Guidebook 

      Standard Areas:              Standard Durations:
           100 km²                      24 hours
           500 km²                      36 hours
         1,000 km²                      48 hours
         2,500 km²                      72 hours
         5,000 km²                      96 hours (NSW only)
        10,000 km² 
        20,000 km²
        40,000 km²

       Sample:coastal_1000.xls (temporal distribution of PMP)
       COASTAL 1,000 KM²
       24HOURS
       Time_hrs  Time_%  Incremental_%  Cumulative_%
           3     12.5         6.23          6.2
           6     25          10.32         16.5
           9     37.5        14.51         31.1
          12     50          19.39         50.4
          15     62.5        16.75         67.2
          18     75          14.64         81.8
          21     87.5        10.39         92.2
          24    100           7.77        100
       36HOURS and so on up to 96 hours.

       Key to Temporal Distribution Headings
       Time_hrs:
          The time elapsed from the start of the standard burst
          duration to its end, in intervals of 3 hours. 
       Time_%:
          The elapsed time expressed as a percentage of the
          standard burst duration.
       Incremental_% (design PMP.files):
          The percentage of the total rainfall depth that fell in
          the preceding 3 hourly segment of the standard burst
          duration as derived using the AVM.
       Cumulative_% (design PMP files):
          The percentage of the total rainfall depth that fell up
          to that time within the standard burst duration as 
          derived using the AVM.

       Sample:pre_burst_coastal.xls (pre-burst temporal 
                                       distribution) 
       COASTAL   PRE-BURST   ALL AREAS
       12HOURS
       Hours_Prior  Incremental_%  Cumulative_%
           42          0.00           0.00
           39          1.96           1.96
           36          0.89           2.85
           33          1.04           3.89
           30          1.63           5.52
           27          2.32           7.84
           24          1.81           9.65
           21          2.13          11.79
           18          2.59          14.37
           15          2.89          17.26
           12          2.52          19.78
            9          2.83          22.62
            6          3.09          25.71
            3          3.31          29.02
       24HOURS and so on up to 120 hours.

       Key to Pre-burst Temporal Distribution Headings
       Hours_Prior:
          The hours prior to the beginning of the design rainfall 
          burst in 3-hourly intervals.
       Incremental_%:
          The percentage of the total design rainfall burst
          falling in each 3-hourly interval prior to the burst.
       Cumulative_% (design PMP files):
          The percentage of the total design rainfall burst
          falling up to this many hours prior to the burst.


(7) worked_examples/
 
  7.1 test_catchment_a.dbf
  7.2 test_catchment_a.prj
  7.3 test_catchment_a.shp
  7.4 test_catchment_a.shx

  7.5 test_catchment_b.dbf
  7.6 test_catchment_b.prj
  7.7 test_catchment_b.shp
  7.8 test_catchment_b.shx

  These are shapefiles for two hypothetical catchments suitable 
  for viewing using GIS software. They are for use in working
  through the examples of applying the GSAM given in Section 5
  of the Guidebook. 
 
