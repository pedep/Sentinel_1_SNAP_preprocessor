import zipfile
from osgeo import gdal
# import xml.etree.ElementTree as ET
import os
import sys
import geopandas as gpd
import numpy as np
import rasterio as rio
# from rasterio.mask import mask
# from rasterio.windows import Window
# from rasterio.transform import from_origin
from pathlib import Path
import glob
import shutil
import uuid
import pyproj
import pickle

class Utils(object):

    def gdal_error_handler(err_class, err_num, err_msg):
        errtype = {
                gdal.CE_None:'None',
                gdal.CE_Debug:'Debug',
                gdal.CE_Warning:'Warning',
                gdal.CE_Failure:'Failure',
                gdal.CE_Fatal:'Fatal'
        }
        err_msg = err_msg.replace('\n',' ')
        err_class = errtype.get(err_class, 'None')
        print('Error Number: %s' % (err_num))
        print('Error Type: %s' % (err_class))
        print('Error Message: %s' % (err_msg))
        

    def check_pkl_file(input_dir):
        pkl_file = Utils.file_list_from_dir('' + '*.pkl')
        if not pkl_file:
            print('## No mean data found for SAR2SAR!')
            sys.exit()

        with open(pkl_file, 'rb') as f:
            mean_dict = pickle.load(f)

        input_files = Utils.file_list_from_dir(input_dir + '*.tif')
        input_files = [os.path.splitext(file)[0][:-3] for file in input_files]
        input_files = list(set(input_files))

        if not len(input_files) == len(mean_dict) / 2:
            print('# Mismatch in input file amount and mean data amount! Files may be missing!')
            print(f'# {len(input_files)} files in input')
            print(f'# {len(mean_dict) / 2} * 2 lines of data available')
            print(f'# Ensure mean data extractor has been running on same SAFE files as has been input')
            terminator  = 'a'

        for filename in mean_dict:
            if not filename in input_files:
                print(f'# {filename} not present in list!')
                terminator = 'a'
            if 'terminator' in locals(): sys.exit()
        return


    def file_list_from_dir(directory, extension, accept_no_files = False):
        file_list = glob.glob(directory + extension)
        if len(file_list) == 0 and accept_no_files == False:
            print('## No ' + extension + ' files in input!')
            sys.exit()

        return file_list
    
    
    def is_valid_epsg(epsg_code):
        try:
            pyproj.CRS.from_epsg(epsg_code)
            return True
        except pyproj.exceptions.CRSError:
            return False
        

    def check_create_folder(directory):
        Path(directory).mkdir(exist_ok = True)
    

    def shape_to_geojson(output, shape):
        shp_file = gpd.read_file(shape)
        geojson = output + 'tmp.geojson'
        shp_file.to_file(geojson, driver='GeoJSON')
        return geojson


    def extract_polarization_band(geotiff_output_dir, input_file, polarization):
        gdal.UseExceptions()

        extension = Path(input_file).suffix
        input_dataset = gdal.Open(input_file, gdal.GA_ReadOnly)

        for subdataset in input_dataset.GetSubDatasets():

            subdataset_name, _ = subdataset
            band = gdal.Open(subdataset_name)
            metadata = band.GetMetadata()

            band_type = subdataset_name[-5:][:2]
            orbit = metadata['/Metadata_Group/Abstracted_Metadata/NC_GLOBAL#PASS']

            # band = input_dataset.GetRasterBand(band_index)
            # band_type = band.GetMetadata().get('POLARIZATION', '')
            # orbit = input_dataset.GetMetadata().get('ORBIT_DIRECTION', '')

            if orbit == 'ASCENDING': orbit_direction = 'ASC'
            elif orbit == 'DESCENDING': orbit_direction = 'DSC'
            else: 
                print('# Orbital direction error!')
                sys.exit()

            if band_type in polarization:
                translate_options = gdal.TranslateOptions(
                    format = "GTiff",
                    options = ["TILED=YES", "COMPRESS=LZW"],
                    # outputType = gdal.GDT_Float32
                    # outputType = gdal.GDT_Int16
                )

                band_info = band_type + '_' + orbit_direction
                
                filename = os.path.basename(input_file).replace(extension, '_') + band_info + "_band.tif"
                output_geotiff = os.path.join(geotiff_output_dir, filename)

                gdal.Translate(output_geotiff, band, options=translate_options)

        input_dataset = None        
        return
    

    def unzip_data_to_dir(data, tmp):
        unzipped_safe = tmp + str(uuid.uuid4())
        Path(unzipped_safe).mkdir(exist_ok = True)
        with zipfile.ZipFile(data, 'r') as zip_ref:
            zip_ref.extractall(unzipped_safe)
        
        return unzipped_safe
    

    def remove_folder(folder):
        shutil.rmtree(folder)
    
    
    def crs_warp(dataset, crs, output):
        gdal.UseExceptions()

        gdal_dataset = gdal.Open(dataset)

        geotransform = gdal_dataset.GetGeoTransform()
        x_res = geotransform[1]
        y_res = -geotransform[5]

        options = gdal.WarpOptions(format = "GTiff", dstSRS = crs, xRes=x_res, yRes=y_res, resampleAlg=gdal.GRA_NearestNeighbour)     
        gdal.Warp(output, gdal_dataset, options = options)
        shutil.move(output, dataset)

    
    def create_sorted_outputs(output, polarization):

        output = output + 'sorted_denoised_geotiffs/'
        Path(output).mkdir(exist_ok = True)

        for pol in polarization:
            Path(output + pol + '_' + 'ASC/').mkdir(exist_ok = True)
            Path(output + pol + '_' + 'DSC/').mkdir(exist_ok = True)
        return output
    
    def sort_outputs(tif, polarization, output):
        file_polarization = None
        for pol in polarization:
            if pol in tif:  file_polarization = pol
        if file_polarization == None: print('# ERROR: No polarization information in file!')

        orbit_dir = None
        if '_ASC_' in tif: orbit_dir = 'ASC'
        elif '_DSC_' in tif: orbit_dir = 'DSC'
        if orbit_dir == None: print('# ERROR: No orbital direction information in file!')

        if None in (file_polarization, orbit_dir):
            Path(output + 'unsorted/').mkdir(exist_ok = True)
            shutil.copyfile(tif, output + 'unsorted/')
            return

        sort_dir = output + file_polarization + '_' + orbit_dir + '/'
        sort_filename = sort_dir + os.path.basename(tif)
        shutil.copyfile(tif, sort_filename)

        return
    
    
    def db_to_linear(db_geotiff):
        with rio.open(db_geotiff, 'r+') as src:
            sar_db = src.read(1)

            sar_db[sar_db > 0] = 0  #removing positive decibel values improves denoising outout
            sar_linear = 10.0 ** (sar_db / 10.0)
            sar_linear = sar_linear * 200

            src.write(sar_linear, 1)
        return 


    def linear_to_db(lin_geotiff):
        with rio.open(lin_geotiff, 'r+') as src:
            sar_linear = src.read(1)

            sar_linear = sar_linear / 200
            sar_db = 10.0 * np.log10(sar_linear)

            src.write(sar_db, 1)
        return 
    
    
    def get_references(input_file_list):

        #largest file will in all likelihood contain an image which overlaps whole shape
        reference_file = max(input_file_list, key=os.path.getsize)

        reference = gdal.Open(reference_file)
        reference_geotransform = reference.GetGeoTransform()
        reference_projection = reference.GetProjection()
        reference = None

        return reference_projection, reference_geotransform
    

    def align_raster(raster_path, output_path, reference_projection, reference_geotransform):

        gdal.Warp(output_path,
                raster_path,
                xRes=reference_geotransform[1],
                yRes=-reference_geotransform[5],
                targetAlignedPixels=True,
                resampleAlg=gdal.GRA_NearestNeighbour
                )
        
        shutil.move(output_path, raster_path)
        
