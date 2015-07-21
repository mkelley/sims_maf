#! /usr/bin/env python
import os, sys, argparse
import numpy as np
# Set matplotlib backend (to create plots where DISPLAY is not set).
import matplotlib
matplotlib.use('Agg')
import matplotlib.pylab as plt
import healpy as hp
import warnings

import lsst.sims.maf.db as db
import lsst.sims.maf.metrics as metrics
import lsst.sims.maf.slicers as slicers
import lsst.sims.maf.stackers as stackers
import lsst.sims.maf.plots as plots
import lsst.sims.maf.metricBundles as metricBundles
import lsst.sims.maf.utils as utils


def makeBundleList(dbFile, runName=None, nside=128, benchmark='design',
                   lonCol='fieldRA', latCol='fieldDec'):
    """
    make a list of metricBundle objects to look at the scientific performance
    of an opsim run.
    """

    # List to hold everything we're going to make
    bundleList = []

    # Connect to the databse
    opsimdb = utils.connectOpsimDb(dbFile)
    if runName is None:
        runName = os.path.basename(dbFile).replace('_sqlite.db', '')

    # Fetch the proposal ID values from the database
    propids, propTags = opsimdb.fetchPropInfo()

    # Fetch the telescope location from config
    lat, lon, height = opsimdb.fetchLatLonHeight()

    # Add metadata regarding dithering/non-dithered.
    commonname = ''.join([a for a in lonCol if a in latCol])
    if commonname == 'field':
        slicermetadata = ' (non-dithered)'
    else:
        slicermetadata = ' (%s)' %(commonname)


    # Construct a WFD SQL where clause so multiple propIDs can query by WFD:
    wfdWhere = utils.createSQLWhere('WFD', propTags)
    print '#FYI: WFD "where" clause: %s' %(wfdWhere)
    ddWhere = utils.createSQLWhere('DD', propTags)
    print '#FYI: DD "where" clause: %s' %(ddWhere)

    # Fetch the total number of visits (to create fraction for number of visits per proposal)
    totalNVisits = opsimdb.fetchNVisits()

    # Set up benchmark values, scaled to length of opsim run.
    runLength = opsimdb.fetchRunLength()
    if benchmark == 'requested':
        # Fetch design values for seeing/skybrightness/single visit depth.
        benchmarkVals = utils.scaleBenchmarks(runLength, benchmark='design')
        # Update nvisits with requested visits from config files.
        benchmarkVals['nvisits'] = opsimdb.fetchRequestedNvisits(propId=proptags['WFD'])
        # Calculate expected coadded depth.
        benchmarkVals['coaddedDepth'] = utils.calcCoaddedDepth(benchmarkVals['nvisits'], benchmarkVals['singleVisitDepth'])
    elif (benchmark == 'stretch') or (benchmark == 'design'):
        # Calculate benchmarks for stretch or design.
        benchmarkVals = utils.scaleBenchmarks(runLength, benchmark=benchmark)
        benchmarkVals['coaddedDepth'] = utils.calcCoaddedDepth(benchmarkVals['nvisits'], benchmarkVals['singleVisitDepth'])
    else:
        raise ValueError('Could not recognize benchmark value %s, use design, stretch or requested.' %(benchmark))
    # Check that nvisits is not set to zero (for very short run length).
    for f in benchmarkVals['nvisits']:
        if benchmarkVals['nvisits'][f] == 0:
            print 'Updating benchmark nvisits value in %s to be nonzero' %(f)
            benchmarkVals['nvisits'][f] = 1


    # Set values for min/max range of nvisits for All/WFD and DD plots. These are somewhat arbitrary.
    nvisitsRange = {}
    nvisitsRange['all'] = {'u':[20, 80], 'g':[50,150], 'r':[100, 250],
                           'i':[100, 250], 'z':[100, 300], 'y':[100,300]}
    nvisitsRange['DD'] = {'u':[6000, 10000], 'g':[2500, 5000], 'r':[5000, 8000],
                          'i':[5000, 8000], 'z':[7000, 10000], 'y':[5000, 8000]}
    # Scale these ranges for the runLength.
    scale = runLength / 10.0
    for prop in nvisitsRange:
        for f in nvisitsRange[prop]:
            for i in [0, 1]:
                nvisitsRange[prop][f][i] = int(np.floor(nvisitsRange[prop][f][i] * scale))

    # Filter list, and map of colors (for plots) to filters.
    filters = ['u','g','r','i','z','y']
    colors={'u':'cyan','g':'g','r':'y','i':'r','z':'m', 'y':'k'}
    filtorder = {'u':1,'g':2,'r':3,'i':4,'z':5,'y':6}

    # Set up a list of common summary stats
    commonSummary = [metrics.MeanMetric(), metrics.RobustRmsMetric(), metrics.MedianMetric(),
                     metrics.PercentileMetric(metricName='25th%ile', percentile=25),
                     metrics.PercentileMetric(metricName='75th%ile', percentile=75),
                     metrics.MinMetric(), metrics.MaxMetric()]
    allStats = commonSummary

    # Set up some 'group' labels
    reqgroup = 'A: Required SRD metrics'
    depthgroup = 'B: Depth per filter'
    uniformitygroup = 'C: Uniformity'
    seeinggroup = 'D: Seeing distribution'


    # Set up an object to track the metricBundles that we want to combine into merged plots.
    mergedHistDict = {}

    # Set the histogram merge function.
    mergeFunc = plots.HealpixHistogram()

    keys = ['NVisits', 'coaddm5', 'NormEffTime', 'Minseeing', 'seeingAboveLimit', 'minAirmass',
            'fracAboveAirmass']

    for key in keys:
        mergedHistDict[key] = plots.PlotBundle(plotFunc=mergeFunc)

    ##
    # Calculate the fO metrics for all proposals and WFD only.
    order = 0
    for prop in ('All prop', 'WFD only'):
        if prop == 'All prop':
            metadata = 'All Visits' + slicermetadata
            sqlconstraint = ''
        if prop == 'WFD only':
            metadata = 'WFD only' + slicermetadata
            sqlconstraint = '%s' %(wfdWhere)
        # Configure the count metric which is what is used for f0 slicer.
        m1 = metrics.CountMetric(col='expMJD', metricName='fO')
        plotDict={'xlabel':'Number of Visits','Asky':benchmarkVals['Area'],
                  'Nvisit':benchmarkVals['nvisitsTotal'],
                  'xMin':0, 'xMax':1500}
        summaryMetrics=[metrics.fOArea(nside=nside, norm=False, metricName='fOArea: Nvisits (#)',
                                       Asky=benchmarkVals['Area'], Nvisit=benchmarkVals['nvisitsTotal']),
                        metrics.fOArea(nside=nside, norm=True, metricName='fOArea: Nvisits/benchmark',
                                       Asky=benchmarkVals['Area'], Nvisit=benchmarkVals['nvisitsTotal']),
                        metrics.fONv(nside=nside, norm=False, metricName='fONv: Area (sqdeg)',
                                     Asky=benchmarkVals['Area'], Nvisit=benchmarkVals['nvisitsTotal']),
                        metrics.fONv(nside=nside, norm=True, metricName='fONv: Area/benchmark',
                                     Asky=benchmarkVals['Area'], Nvisit=benchmarkVals['nvisitsTotal'])]
        caption = 'The FO metric evaluates the overall efficiency of observing. '
        caption += 'fOArea: Nvisits = %.1f sq degrees receive at least this many visits out of %d. ' %(benchmarkVals['Area'], benchmarkVals['nvisitsTotal'])
        caption += 'fONv: Area = this many square degrees out of %.1f receive at least %d visits.' %(benchmarkVals['Area'], benchmarkVals['nvisitsTotal'])
        displayDict={'group':reqgroup, 'subgroup':'F0', 'displayOrder':order, 'caption':caption}
        order += 1
        slicer = slicers.HealpixSlicer(nside=nside, lonCol=lonCol, latCol=latCol)

        bundle = metricBundles.MetricBundle(m1, slicer, sqlconstraint, plotDict=plotDict,
                                            displayDict=displayDict, summaryMetrics=summaryMetrics,
                                            plotFuncs=[plots.FOPlot()],
                                            runName=runName, metadata=metadata)
        bundleList.append(bundle)

    ###
    # Calculate the Rapid Revisit Metrics.
    order = 0
    metadata = 'All Visits' + slicermetadata
    sqlconstraint = ''
    dTmin = 40.0 # seconds
    dTmax = 30.0 # minutes
    minNvisit = 100
    pixArea = float(hp.nside2pixarea(nside, degrees=True))
    scale = pixArea * hp.nside2npix(nside)
    cutoff1 = 0.15
    extraStats1 = [metrics.FracBelowMetric(cutoff=cutoff1, scale=scale, metricName='Area (sq deg)')]
    extraStats1.extend(commonSummary)
    slicer = slicers.HealpixSlicer(nside=nside, lonCol=lonCol, latCol=latCol)
    m1 = metrics.RapidRevisitMetric(metricName='RapidRevisitUniformity',
                                    dTmin=dTmin/60.0/60.0/24.0, dTmax=dTmax/60.0/24.0,
                                    minNvisits=minNvisit)

    plotDict={'xMin':0, 'xMax':1}
    summaryStats=extraStats1
    caption = 'Deviation from uniformity for short revisit timescales, between %s and %s seconds, ' %(dTmin, dTmax)
    caption += 'for pointings with at least %d visits in this time range. ' %(minNvisit)
    caption += 'Summary statistic "Area" below indicates the area on the sky which has a deviation from uniformity of < %.2f.' %(cutoff1)
    displayDict = {'group':reqgroup, 'subgroup':'Rapid Revisit', 'displayOrder':order, 'caption':caption}
    bundle = metricBundles.MetricBundle(m1, slicer, sqlconstraint, plotDict=plotDict,
                                        displayDict=displayDict, summaryMetrics=summaryStats,
                                        runName=runName, metadata=metadata)
    bundleList.append(bundle)
    order += 1

    m2 = metrics.NRevisitsMetric(dT=dTmax)
    plotDict={'xMin':0, 'xMax':1000}
    cutoff2 = 800
    extraStats2 = [metrics.FracAboveMetric(cutoff=cutoff2, scale=scale, metricName='Area (sq deg)')]
    extraStats2.extend(commonSummary)
    caption = 'Number of consecutive visits with return times faster than %.1f minutes, in any filter, all proposals. ' %(dTmax)
    caption += 'Summary statistic "Area" below indicates the area on the sky which has more than %d revisits within this time window.' %(cutoff2)
    summaryStats= extraStats2
    displayDict = {'group':reqgroup, 'subgroup':'Rapid Revisit', 'displayOrder':order, 'caption':caption}
    bundle = metricBundles.MetricBundle(m2, slicer, sqlconstraint, plotDict=plotDict,
                                        displayDict=displayDict, summaryMetrics=summaryStats,
                                        runName=runName, metadata=metadata)
    bundleList.append(bundle)
    order += 1
    m3 = metrics.NRevisitsMetric(dT=dTmax, normed=True)
    plotDict={'xMin':0, 'xMax':1}
    cutoff3 = 0.6
    extraStats3 = [metrics.FracAboveMetric(cutoff=cutoff3, scale=scale, metricName='Area (sq deg)')]
    extraStats3.extend(commonSummary)
    summaryStats= extraStats3
    caption = 'Fraction of total visits where consecutive visits have return times faster than %.1f minutes, in any filter, all proposals. ' %(dTmax)
    caption += 'Summary statistic "Area" below indicates the area on the sky which has more than %d revisits within this time window.' %(cutoff3)
    displayDict = {'group':reqgroup, 'subgroup':'Rapid Revisit', 'displayOrder':order, 'caption':caption}
    bundle = metricBundles.MetricBundle(m3, slicer, sqlconstraint, plotDict=plotDict,
                                        displayDict=displayDict, summaryMetrics=summaryStats,
                                        runName=runName, metadata=metadata)
    bundleList.append(bundle)
    order += 1


    # And add a histogram of the time between quick revisits.
    binMin = 0
    binMax = 120.
    binsize= 3.
    bins = np.arange(binMin/60.0/24.0, (binMax+binsize)/60./24., binsize/60./24.)
    m1 = metrics.TgapsMetric(bins=bins, metricName='dT visits')
    plotDict={'bins':bins, 'xlabel':'dT (minutes)'}
    displayDict={'group':reqgroup, 'subgroup':'Rapid Revisit', 'order':order,
                 'caption':'Histogram of the time between consecutive revisits (<%.1f minutes), over entire sky.' %(binMax)}
    slicer = slicers.HealpixSlicer(nside=nside, lonCol=lonCol, latCol=latCol)
    plotFunc = plots.SummaryHistogram()
    bundle = metricBundles.MetricBundle(m1, slicer, sqlconstraint, plotDict=plotDict,
                                        displayDict=displayDict, runName=runName, metadata=metadata, plotFuncs=[plotFunc])
    bundleList.append(bundle)
    order += 1


    ##
    # Trigonometric parallax and proper motion @ r=20 and r=24
    slicer = slicers.HealpixSlicer(nside=nside, lonCol=lonCol, latCol=latCol)
    sqlconstraint = ''
    order = 0
    metric = metrics.ParallaxMetric(metricName='Parallax 20', rmag=20)
    summaryStats=allStats
    plotDict={'cbarFormat':'%.1f', 'xMin':0, 'xMax':3}
    displayDict={'group':reqgroup, 'subgroup':'Parallax', 'order':order,
                 'caption':'Parallax precision at r=20. (without refraction).'}
    bundle = metricBundles.MetricBundle(metric, slicer, sqlconstraint, plotDict=plotDict,
                                        displayDict=displayDict, summaryMetrics=summaryStats,
                                        runName=runName, metadata=metadata)
    bundleList.append(bundle)
    order += 1
    metric=metrics.ParallaxMetric(metricName='Parallax 24', rmag=24)
    plotDict={'cbarFormat':'%.1f', 'xMin':0, 'xMax':10}
    displayDict={'group':reqgroup, 'subgroup':'Parallax', 'order':order,
                 'caption':'Parallax precision at r=24. (without refraction).'}
    bundle = metricBundles.MetricBundle(metric, slicer, sqlconstraint, plotDict=plotDict,
                                        displayDict=displayDict, summaryMetrics=summaryStats,
                                        runName=runName, metadata=metadata)
    bundleList.append(bundle)
    order += 1
    metric=metrics.ParallaxMetric(metricName='Parallax Normed', rmag=24, normalize=True)
    plotDict={'xMin':0.5, 'xMax':1.0}
    displayDict={'group':reqgroup, 'subgroup':'Parallax', 'order':order,
                 'caption':
                 'Normalized parallax (normalized to optimum observation cadence, 1=optimal).'}
    bundle = metricBundles.MetricBundle(metric, slicer, sqlconstraint, plotDict=plotDict,
                                        displayDict=displayDict, summaryMetrics=summaryStats,
                                        runName=runName, metadata=metadata)
    bundleList.append(bundle)
    order += 1
    metric=metrics.ProperMotionMetric(metricName='Proper Motion 20', rmag=20)
    summaryStats=allStats
    plotDict={'xMin':0, 'xMax':3}
    displayDict={'group':reqgroup, 'subgroup':'Proper Motion', 'order':order,
                 'caption':'Proper Motion precision at r=20.'}
    bundle = metricBundles.MetricBundle(metric, slicer, sqlconstraint, plotDict=plotDict,
                                        displayDict=displayDict, summaryMetrics=summaryStats,
                                        runName=runName, metadata=metadata)
    bundleList.append(bundle)
    order += 1
    metric=metrics.ProperMotionMetric(rmag=24, metricName='Proper Motion 24')
    summaryStats=allStats
    plotDict={'xMin':0, 'xMax':10}
    displayDict={'group':reqgroup, 'subgroup':'Proper Motion', 'order':order,
                 'caption':'Proper Motion precision at r=24.'}
    bundle = metricBundles.MetricBundle(metric, slicer, sqlconstraint, plotDict=plotDict,
                                        displayDict=displayDict, summaryMetrics=summaryStats,
                                        runName=runName, metadata=metadata)
    bundleList.append(bundle)
    order += 1
    metric=metrics.ProperMotionMetric(rmag=24,normalize=True, metricName='Proper Motion Normed')
    plotDict={'xMin':0.2, 'xMax':0.7}
    displayDict={'group':reqgroup, 'subgroup':'Proper Motion', 'order':order,
                 'caption':'Normalized proper motion at r=24 (normalized to optimum observation cadence - start/end. 1=optimal).'}
    bundle = metricBundles.MetricBundle(metric, slicer, sqlconstraint, plotDict=plotDict,
                                        displayDict=displayDict, summaryMetrics=summaryStats,
                                        runName=runName, metadata=metadata)
    bundleList.append(bundle)
    order += 1

    ##
    # Calculate the time uniformity in each filter, for each year.
    order = 0
    yearDates = range(0,int(round(365*runLength))+365,365)
    slicer = slicers.HealpixSlicer(nside=nside, lonCol=lonCol, latCol=latCol)
    for i in range(len(yearDates)-1):
        for f in filters:
            metadata = '%s band, after year %d' %(f, i+1) + slicermetadata
            sqlconstraint = 'filter = "%s" and night<=%i' %(f, yearDates[i+1])
            metric = metrics.UniformityMetric(metricName='Time Uniformity')
            plotDict={'xMin':0, 'xMax':1}
            caption = 'Deviation from uniformity in %s band, by the end of year %d of the survey. ' %(f, i+1)
            caption += '(0=perfectly uniform, 1=perfectly nonuniform).'
            displayDict = {'group':uniformitygroup, 'subgroup':'At year %d' %(i+1),
                           'displayOrder':filtorder[f], 'caption': caption}
            bundle = metricBundles.MetricBundle(metric, slicer, sqlconstraint, plotDict=plotDict,
                                                displayDict=displayDict, runName=runName, metadata=metadata)
            bundleList.append(bundle)

    ##
    # Depth metrics.
    slicer = slicers.HealpixSlicer(nside=nside, lonCol=lonCol, latCol=latCol)
    for f in filters:
        propCaption = '%s band, all proposals %s' %(f, slicermetadata)
        sqlconstraint = 'filter = "%s"' %(f)
        metadata = '%s band' %(f) + slicermetadata
        # Number of visits.
        metric = metrics.CountMetric(col='expMJD', metricName='NVisits')
        plotDict={'xlabel':'Number of visits',
                  'xMin':nvisitsRange['all'][f][0],
                  'xMax':nvisitsRange['all'][f][1], 'binsize':5}
        summaryStats=allStats
        displayDict={'group':depthgroup, 'subgroup':'Nvisits', 'order':filtorder[f],
                     'caption':'Number of visits in filter %s, %s.' %(f, propCaption)}
        histMerge={'color':colors[f], 'label':'%s'%(f),
                   'binsize':5,
                   'xMin':nvisitsRange['all'][f][0], 'xMax':nvisitsRange['all'][f][1],
                   'legendloc':'upper right'}
        bundle = metricBundles.MetricBundle(metric, slicer, sqlconstraint, plotDict=plotDict,
                                            displayDict=displayDict, runName=runName, metadata=metadata,
                                            summaryMetrics=summaryStats)
        mergedHistDict['NVisits'].addBundle(bundle,plotDict=histMerge)
        bundleList.append(bundle)
        # Coadded depth.
        metric = metrics.Coaddm5Metric()
        plotDict={'zp':benchmarkVals['coaddedDepth'][f], 'xMin':-0.8, 'xMax':0.8,
                  'xlabel':'coadded m5 - %.1f' %benchmarkVals['coaddedDepth'][f]}
        summaryStats=allStats
        histMerge={'legendloc':'upper right', 'color':colors[f], 'label':'%s' %f, 'binsize':.02,
                   'xlabel':'coadded m5 - benchmark value'}
        caption = 'Coadded depth in filter %s, with %s value subtracted (%.1f), %s. More positive numbers indicate fainter limiting magnitudes.'\
            %(f, benchmark, benchmarkVals['coaddedDepth'][f], propCaption)
        displayDict={'group':depthgroup, 'subgroup':'Coadded Depth',
                     'order':filtorder[f],'caption':caption}
        bundle = metricBundles.MetricBundle(metric, slicer, sqlconstraint, plotDict=plotDict,
                                            displayDict=displayDict, runName=runName,  metadata=metadata,
                                            summaryMetrics=summaryStats)
        mergedHistDict['coaddm5'].addBundle(bundle,plotDict=histMerge)
        bundleList.append(bundle)
        # Effective time.
        metric = metrics.TeffMetric(metricName='Normalized Effective Time',normed=True)
        plotDict={'xMin':0.1, 'xMax':1.1}
        summaryStats=allStats
        histMerge={'legendLoc':'upper right', 'color':colors[f], 'label':'%s' %f, 'binsize':0.02}
        caption = '"Time Effective" in filter %s, calculated with fiducial depth %s. '%(f, benchmarkVals['singleVisitDepth'][f])
        caption += 'Normalized by the fiducial time effective, if every observation was at the fiducial depth.'
        displayDict={'group':depthgroup, 'subgroup':'Time Eff.', 'order':filtorder[f], 'caption':caption}
        bundle = metricBundles.MetricBundle(metric, slicer, sqlconstraint, plotDict=plotDict,
                                            displayDict=displayDict, runName=runName, metadata=metadata,
                                            summaryMetrics=summaryStats)
        mergedHistDict['NormEffTime'].addBundle(bundle,plotDict=histMerge)
        bundleList.append(bundle)

    # Good seeing in r/i band metrics, including in first/second years.
    order = 0
    for tcolor, tlabel, timespan in zip(['k', 'g', 'r'], ['10 years', '1 year', '2 years'],
                                        ['', ' and night<=365', ' and night<=730']):
        order += 1
        for f in (['r', 'i']):
            sqlconstraint = 'filter = "%s" %s' %(f, timespan)
            propCaption = '%s band, all proposals %s, over %s.' %(f, slicermetadata, tlabel)
            metadata = '%s band, %s' %(f, tlabel) + slicermetadata
            seeing_limit = 0.7
            airmass_limit = 1.2
            metric = metrics.MinMetric(col='finSeeing')
            summaryStats=allStats
            plotDict={'xMin':0.35, 'xMax':0.9, 'color':tcolor}
            displayDict={'group':seeinggroup, 'subgroup':'Best Seeing',
                         'order':filtorder[f]*100+order,
                         'caption':'Minimum seeing values in %s.' %(propCaption)}
            histMerge={'label':'%s %s' %(f, tlabel), 'color':tcolor,
                       'binsize':0.03, 'xMin':0.35, 'xMax':0.9, 'legendloc':'upper right'}
            bundle = metricBundles.MetricBundle(metric, slicer, sqlconstraint, plotDict=plotDict,
                                            displayDict=displayDict, runName=runName, metadata=metadata,
                                            summaryMetrics=summaryStats)
            mergedHistDict['Minseeing'].addBundle(bundle,plotDict=histMerge)
            bundleList.append(bundle)

            metric = metrics.FracAboveMetric(col='finSeeing', cutoff = seeing_limit)
            summaryStats=allStats
            plotDict={'xMin':0, 'xMax':1, 'color':tcolor}
            displayDict={'group':seeinggroup, 'subgroup':'Good seeing fraction',
                         'order':filtorder[f]*100+order,
                         'caption':'Fraction of total images with seeing worse than %.1f, in %s'
                         %(seeing_limit, propCaption)}
            histMerge={'color':tcolor, 'label':'%s %s' %(f, tlabel),
                       'binsize':0.05, 'legendloc':'upper right'}
            bundle = metricBundles.MetricBundle(metric, slicer, sqlconstraint, plotDict=plotDict,
                                            displayDict=displayDict, runName=runName, metadata=metadata,
                                            summaryMetrics=summaryStats)
            mergedHistDict['seeingAboveLimit'].addBundle(bundle,plotDict=histMerge)
            bundleList.append(bundle)

            metric = metrics.MinMetric(col='airmass')
            plotDict={'xMin':1, 'xMax':1.5, 'color':tcolor}
            summaryStats=allStats
            displayDict={'group':seeinggroup, 'subgroup':'Best Airmass',
                         'order':filtorder[f]*100+order, 'caption':
                         'Minimum airmass in %s.' %(propCaption)}
            histMerge={'color':tcolor, 'label':'%s %s' %(f, tlabel),
                       'binsize':0.03, 'legendloc':'upper right'}
            bundle = metricBundles.MetricBundle(metric, slicer, sqlconstraint, plotDict=plotDict,
                                            displayDict=displayDict, runName=runName, metadata=metadata,
                                            summaryMetrics=summaryStats)
            mergedHistDict['minAirmass'].addBundle(bundle,plotDict=histMerge)
            bundleList.append(bundle)

            metric= metrics.FracAboveMetric(col='airmass', cutoff=airmass_limit)
            plotDict={'xMin':0, 'xMax':1, 'color':tcolor}
            summaryStats=allStats
            displayDict={'group':seeinggroup, 'subgroup':'Low airmass fraction',
                         'order':filtorder[f]*100+order, 'caption':
                         'Fraction of total images with airmass higher than %.2f, in %s'
                         %(airmass_limit, propCaption)}
            histMerge={'color':tcolor, 'label':'%s %s' %(f, tlabel), 'binsize':0.05, 'legendloc':'upper right'}

            bundle = metricBundles.MetricBundle(metric, slicer, sqlconstraint, plotDict=plotDict,
                                                displayDict=displayDict, runName=runName, metadata=metadata,
                                                summaryMetrics=summaryStats)
            mergedHistDict['fracAboveAirmass'].addBundle(bundle,plotDict=histMerge)
            bundleList.append(bundle)

    return metricBundles.makeBundlesDictFromList(bundleList), mergedHistDict


if __name__=="__main__":

    parser = argparse.ArgumentParser(description='Python script to run MAF with the science performance metrics')
    parser.add_argument('dbFile', type=str, default=None,help="full file path to the opsim sqlite file")

    parser.add_argument("--outDir",type=str, default='./Out', help='Output directory for MAF outputs. Default "Out"')
    parser.add_argument("--nside", type=int, default=128,
                        help="Resolution to run Healpix grid at (must be 2^x). Default 128.")
    parser.add_argument("--lonCol", type=str, default='fieldRA',
                        help="Column to use for RA values (can be a stacker dither column). Default=fieldRA.")
    parser.add_argument("--latCol", type=str, default='fieldDec',
                        help="Column to use for Dec values (can be a stacker dither column). Default=fieldDec.")
    parser.add_argument('--benchmark', type=str, default='design',
                        help="Can be 'design' or 'requested'")
    parser.add_argument('--plotOnly', dest='plotOnly', action='store_true',
                        default=False, help="Reload the metric values from disk and re-plot them.")

    parser.set_defaults()
    args, extras = parser.parse_known_args()

    # Build metric bundles.
    bundleDict, mergedHistDict = makeBundleList(args.dbFile, nside=args.nside,
                                                lonCol=args.lonCol, latCol=args.latCol,
                                                benchmark=args.benchmark)

    # Set up / connect to resultsDb.
    resultsDb = db.ResultsDb(outDir=args.outDir)
    # Connect to opsimdb.
    opsdb = utils.connectOpsimDb(args.dbFile)

    # Set up metricBundleGroup.
    group = metricBundles.MetricBundleGroup(bundleDict, opsdb,
                                            outDir=args.outDir, resultsDb=resultsDb)
    # Read or run to get metric values.
    if args.plotOnly:
        group.readAll()
    else:
        group.runAll()
    # Make plots.
    group.plotAll()
    # Make merged plots.
    for key in mergedHistDict:
        if len(mergedHistDict[key].bundleList) > 0:
            mergedHistDict[key].plot(outDir=args.outDir, resultsDb=resultsDb, closeFigs=True)
        else:
            warning.warn('Empty bundleList for %s, skipping merged histogram' % key)
    # Get config info and write to disk.
    utils.writeConfigs(opsdb, args.outDir)

    print "Finished sciencePerformance metric calculations."