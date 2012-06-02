import sys
import time
import zmq
from const import ZMQ_KV8, ZMQ_KV78UWSGI, ZMQ_KV7
from ctx import ctx
from datetime import datetime, timedelta
from time import strftime, gmtime
from gzip import GzipFile
from cStringIO import StringIO
from email.mime.text import MIMEText
import psycopg2
import copy
import smtplib

conn = psycopg2.connect("dbname='kv78turbo' user='postgres'")

tpc_store = {}
stopareacode_store = {}
line_store = {}
journey_store = {}
last_updatedataownerstore = {}
generalmessagestore = {}

tpc_meta = {}
line_meta = {}
destination_meta = {}
kv7cache = {}

def toisotime(operationdate, timestamp, row):
    hours, minutes, seconds = timestamp.split(':')
    if hours == 0 and minutes == 0 and seconds == 0:
    	    return '0000-00-00T00:00'
    hours = int(hours)
    if hours >= 48:
        print row

    if hours >= 24:
        deltadays  = hours / 24
        hours = hours % 24
        years, months, days = operationdate.split('-')
        return (datetime(int(years), int(months), int(days), hours, int(minutes), int(seconds)) + timedelta(days = deltadays)).isoformat()
    else:
        return operationdate+'T'+timestamp

def cleanup(): 	    
    now = datetime.today() - timedelta(seconds=90)
    for timingpointcode, values in tpc_store.items():
    	    if 'Passes' in values:
    	    	    for journey, row in values['Passes'].items():
    	    	    	    if now > datetime.strptime(row['ExpectedArrivalTime'], "%Y-%m-%dT%H:%M:%S") and now > datetime.strptime(row['ExpectedDepartureTime'], "%Y-%m-%dT%H:%M:%S"):
                            	    if 'StopAreaCode' in tpc_store[timingpointcode]['Passes'][journey] and tpc_store[timingpointcode]['Passes'][journey]['StopAreaCode'] != None:
                            	    	    stopareacode = tpc_store[timingpointcode]['Passes'][journey]['StopAreaCode']
                            	    	    del(stopareacode_store[stopareacode][timingpointcode]['Passes'][journey])
                            	    del(tpc_store[timingpointcode]['Passes'][journey])

    for journey_id, values in journey_store.items():
    	    if 'Stops' in values:
    	    	    row = values['Stops'][max(values['Stops'].keys())]
    	    	    if now > datetime.strptime(row['ExpectedArrivalTime'], "%Y-%m-%dT%H:%M:%S") and now > datetime.strptime(row['ExpectedDepartureTime'], "%Y-%m-%dT%H:%M:%S"):
    	    	    	    line_id = row['DataOwnerCode'] + '_' + row['LinePlanningNumber'] + '_' + row['LineDirection']
    	    	    	    if line_id in line_store and journey_id in line_store[line_id]['Actuals']:
    	    	    	    	    del(line_store[line_id]['Actuals'][journey_id])
    	    	    	    if journey_id in journey_store:
    	    	    	    	    del(journey_store[journey_id])
    	    	    	    if journey_id in kv7cache:
    	    	    	    	    del(kv7cache[journey_id])
    	    	    	    	    sys.stdout.write('X')
    	    	    	    	    sys.stdout.flush()

def fetchkv7(row):
	id = '_'.join([row['DataOwnerCode'], row['LocalServiceLevelCode'], row['LinePlanningNumber'], row['JourneyNumber'], row['FortifyOrderNumber']])
	if row['UserStopOrderNumber'] == '1' and row['TripStopStatus'] != 'PASSED':
		cur = conn.cursor()
		cur.execute("SELECT userstopordernumber, targetarrivaltime, targetdeparturetime, productformulatype, destinationname50, linename, linepublicnumber, transporttype from localservicegrouppasstime as ""p"", destination as ""d"", line as ""l"" WHERE p.dataownercode = %s and localservicelevelcode = %s and journeynumber = %s and fortifyordernumber = %s and p.lineplanningnumber = %s and userstopcode = %s AND p.dataownercode = d.dataownercode AND p.destinationcode = d.destinationcode AND p.dataownercode = l.dataownercode AND p.lineplanningnumber = l.lineplanningnumber LIMIT 1;", [row['DataOwnerCode'],row['LocalServiceLevelCode'], row['JourneyNumber'], row['FortifyOrderNumber'], row['LinePlanningNumber'], row['UserStopCode']])
		kv7rows = cur.fetchall()
		for kv7row in kv7rows:
			pass_id = '_'.join([row['UserStopCode'], str(kv7row[0])])
			linemeta_id = row['DataOwnerCode'] + '_' + row['LinePlanningNumber']
			destinationmeta_id = row['DataOwnerCode'] + '_' + row['DestinationCode']
			if id not in kv7cache:
				kv7cache[id] = {pass_id : {'TargetArrivalTime' : toisotime(row['OperationDate'], kv7row[1], row)}}
			else:
				kv7cache[id][pass_id] = {'TargetArrivalTime' : toisotime(row['OperationDate'], kv7row[1], row)}
			kv7cache[id][pass_id]['TargetDepartureTime'] = toisotime(row['OperationDate'], kv7row[2], row)
			kv7cache[id][pass_id]['ProductFormulaType'] = kv7row[3]
			if destinationmeta_id not in destination_meta:
				destination_meta[destinationmeta_id] = kv7row[4]
			if linemeta_id not in line_meta:
				line_meta[linemeta_id] = { 'LineName' : kv7row[5], 'LinePublicNumber' : kv7row[6], 'TransportType' : kv7row[7], 'DataOwnerCode' : row['DataOwnerCode'], 'LinePlanningNumber' : row['LinePlanningNumber']}
	else:
		cur = conn.cursor()
		cur.execute("SELECT targetarrivaltime, targetdeparturetime, productformulatype, destinationname50, linename, linepublicnumber, transporttype from localservicegrouppasstime as ""p"", destination as ""d"", line as ""l"" WHERE p.dataownercode = %s and localservicelevelcode = %s and journeynumber = %s and fortifyordernumber = %s and p.lineplanningnumber = %s and userstopcode = %s and userstopordernumber = %s AND p.dataownercode = d.dataownercode AND p.destinationcode = d.destinationcode AND p.dataownercode = l.dataownercode AND p.lineplanningnumber = l.lineplanningnumber LIMIT 1;", [row['DataOwnerCode'],row['LocalServiceLevelCode'], row['JourneyNumber'], row['FortifyOrderNumber'], row['LinePlanningNumber'], row['UserStopCode'], row['UserStopOrderNumber']])
		kv7rows = cur.fetchall()
		pass_id = '_'.join([row['UserStopCode'], row['UserStopOrderNumber']])
		linemeta_id = row['DataOwnerCode'] + '_' + row['LinePlanningNumber']
		destinationmeta_id = row['DataOwnerCode'] + '_' + row['DestinationCode']
		if len(kv7rows) == 0:
			if id in kv7cache:
				kv7cache[id][pass_id] = {}
			else:
				kv7cache[id] = {pass_id : {}}
			print 'Missing from KV7' + id + '_' + pass_id
		for kv7row in kv7rows:
			if id not in kv7cache:
				kv7cache[id] = {pass_id : {'TargetArrivalTime' : toisotime(row['OperationDate'], kv7row[0], row)}}
			else:
				kv7cache[id][pass_id] = {'TargetArrivalTime' : toisotime(row['OperationDate'], kv7row[0], row)}
			kv7cache[id][pass_id]['TargetDepartureTime'] = toisotime(row['OperationDate'], kv7row[1], row)
			kv7cache[id][pass_id]['ProductFormulaType'] = kv7row[2]
			if destinationmeta_id not in destination_meta:
				destination_meta[destinationmeta_id] = kv7row[3]
			if linemeta_id not in line_meta:
		        	line_meta[linemeta_id] = { 'LineName' : kv7row[4], 'LinePublicNumber' : kv7row[5], 'TransportType' : kv7row[6] , 'DataOwnerCode' : row['DataOwnerCode'], 'LinePlanningNumber' : row['LinePlanningNumber']}
	
def storecurrect(row): 	    
    if row['TripStopStatus'] != 'UNKNOWN' and row['TripStopStatus'] != 'PLANNED': #Keeps status of the dataowners supplying us data
            last_updatedataownerstore[row['DataOwnerCode']] = row['LastUpdateTimeStamp']
    elif row['DataOwnerCode'] not in last_updatedataownerstore:
            last_updatedataownerstore[row['DataOwnerCode']] = 'ERROR'
 
    if row['DataOwnerCode'] == 'EBS' and int(row['LineDirection']) == 0: #Hack for EBS, sigh...
    	    if (int(row['JourneyNumber']) % 2 == 0):
    	    	    row['LineDirection'] = '2'
    	    else:
    	    	    row['LineDirection'] = '1'
    	    	    
    id = '_'.join([row['DataOwnerCode'], row['LocalServiceLevelCode'], row['LinePlanningNumber'], row['JourneyNumber'], row['FortifyOrderNumber']])
    line_id = row['DataOwnerCode'] + '_' + row['LinePlanningNumber'] + '_' + row['LineDirection']
    pass_id = '_'.join([row['DataOwnerCode'], row['LocalServiceLevelCode'], row['LinePlanningNumber'], row['JourneyNumber'], row['FortifyOrderNumber'], row['UserStopCode'], row['UserStopOrderNumber']])
    linemeta_id = row['DataOwnerCode'] + '_' + row['LinePlanningNumber']
    destinationmeta_id = row['DataOwnerCode'] + '_' + row['DestinationCode']
    pass_id = '_'.join([row['UserStopCode'], row['UserStopOrderNumber']])

    if row['TripStopStatus'] == 'CANCEL': #debug for testing CANCELED passes
    	    print 'CANCEL ' + id;

    row['ExpectedArrivalTime'] = toisotime(row['OperationDate'], row['ExpectedArrivalTime'], row)
    row['ExpectedDepartureTime'] = toisotime(row['OperationDate'], row['ExpectedDepartureTime'], row)
        
    if id not in kv7cache or pass_id not in kv7cache[id]:
    	    fetchkv7(row)
    	    sys.stdout.write('M') #debug for detecting missing KV7 packages
    	    sys.stdout.flush()
    # not elif because we want to wait for the fetch from the database
    if id in kv7cache and pass_id in kv7cache[id]:
    	    row.update(kv7cache[id][pass_id])
    	                
    if row['TimingPointCode'] not in tpc_meta:
    	    cur = conn.cursor()
    	    cur.execute("select timingpointname,timingpointtown,stopareacode,CAST(ST_Y(the_geom) AS NUMERIC(9,7)) AS lat,CAST(ST_X(the_geom) AS NUMERIC(8,7)) AS lon FROM (select distinct t.timingpointcode as timingpointcode, t.timingpointname as timingpointname, t.timingpointtown as timingpointtown,t.stopareacode as stopareacode,ST_Transform(st_setsrid(st_makepoint(locationx_ew, locationy_ns), 28992), 4326) AS the_geom from timingpoint as t WHERE timingpointcode = %s) AS W LIMIT 1;", [row['TimingPointCode']])
    	    kv7rows = cur.fetchall()
    	    for kv7row in kv7rows:
    	    	    tpc_meta[row['TimingPointCode']] = {'TimingPointName' : kv7row[0], 'TimingPointTown' : kv7row[1], 'StopAreaCode' : kv7row[2], 'latitude' : kv7row[3], 'longitude' : kv7row[4]} 
            
    try:
        for x in ['JourneyNumber', 'FortifyOrderNumber', 'UserStopOrderNumber', 'NumberOfCoaches']:
            if x in row and row[x] is not None and row[x] != 'UNKNOWN':
                row[x] = int(row[x])

        row['IsTimingStop'] = (row['IsTimingStop'] == '1')
    except:
        raise
    
    if row['TimingPointCode'] not in tpc_store:
    	    tpc_store[row['TimingPointCode']] = {'Passes' : {id: row}, 'GeneralMessages' : {}}
    	    if row['TimingPointCode'] in tpc_meta:
    	    	    tpc_store[row['TimingPointCode']]['Stop'] = tpc_meta[row['TimingPointCode']]
    else:
    	    tpc_store[row['TimingPointCode']]['Passes'][id] = row
    	    
    if row['TimingPointCode'] in tpc_meta:
    	    row.update(tpc_meta[row['TimingPointCode']])
    
    if destinationmeta_id in destination_meta:
    	    row['DestinationName50'] = destination_meta[destinationmeta_id]
    
    if 'StopAreaCode' in row and row['StopAreaCode'] != None:
    	    if row['StopAreaCode'] not in stopareacode_store:
    	    	    stopareacode_store[row['StopAreaCode']] = { row['TimingPointCode'] : {'Passes' : {id : row }}}
    	    elif row['TimingPointCode'] not in stopareacode_store[row['StopAreaCode']]:
    	    	    stopareacode_store[row['StopAreaCode']][row['TimingPointCode']] = {'Passes' : {id : row }}
    	    else:
    	    	    stopareacode_store[row['StopAreaCode']][row['TimingPointCode']]['Passes'][id] = row    	 
    
    if line_id not in line_store:
    	line_store[line_id] = {'Network': {}, 'Actuals': {}, 'Line' : {}}
    	line_store[line_id]['Line'] = {'DataOwnerCode' : row['DataOwnerCode']}
    	line_store[line_id]['Line']['LineDirection'] = row['LineDirection']
    	line_store[line_id]['Line']['LinePlanningNumber'] = row['LinePlanningNumber']
    
    if linemeta_id in line_meta:
    	    row.update(line_meta[linemeta_id])
    	    line_store[line_id]['Line'].update(line_meta[linemeta_id])
    
    if 'DestinationName50' in row:
    	    line_store[line_id]['Line']['DestinationName50'] = row['DestinationName50']
    elif 'DestinationName50' in line_store[line_id]:
    	    del(line_store[line_id]['Line']['DestinationName50'])
    		
    if row['UserStopOrderNumber'] not in line_store[line_id]['Network']:
        line_store[line_id]['Network'][row['UserStopOrderNumber']] = {
            'TimingPointCode': row['TimingPointCode'],
            'IsTimingStop': row['IsTimingStop'],
            'UserStopOrderNumber':row['UserStopOrderNumber']
            }
        if row['TimingPointCode'] in tpc_meta:
            line_store[line_id]['Network'][row['UserStopOrderNumber']].update(tpc_meta[row['TimingPointCode']]) #add tpc metainfo and userstopordernumber to line network

    if id not in journey_store:
    	journey_store[id] = {'Stops' : {row['UserStopOrderNumber']: row}}
    else:
        journey_store[id]['Stops'][row['UserStopOrderNumber']] = row

    if row['TripStopStatus'] in set(['ARRIVED', 'PASSED']): # , 'DRIVING']): Driving alleen nemen als kleinste waarde uit lijn, gegeven dat er geen ARRIVED/PASSED is
    	for key in journey_store[id]['Stops'].keys(): #delete previous stops from journey
            if key < int(row['UserStopOrderNumber']) - 1:
            	del(journey_store[id]['Stops'][key])

        if row['JourneyStopType'] == 'LAST': #delete journey
            if id in line_store[line_id]['Actuals']:
                del(line_store[line_id]['Actuals'][id])
        else:
            line_store[line_id]['Actuals'][id] = row
    elif row['TripStopStatus'] == 'DRIVING':   #replace a passed stop with the next stop
    	previousStopOrder = int(row['UserStopOrderNumber']) - 1
    	if previousStopOrder in journey_store[id]['Stops'] and journey_store[id]['Stops'][previousStopOrder]['TripStopStatus'] == 'PASSED':
    	    line_store[line_id]['Actuals'][id] = row
    elif row['TripStopStatus'] == 'PLANNED' and id not in line_store[line_id]['Actuals'] and int(row['UserStopOrderNumber']) == 1: #add planned journeys
    	line_store[line_id]['Actuals'][id] = row
    elif (row['TripStopStatus'] == 'UNKNOWN' or row['TripStopStatus'] == 'CANCEL') and id in line_store[line_id]['Actuals']: #Delete canceled or non live journeys
	del(line_store[line_id]['Actuals'][id])
            
def storeplanned(row):
	linemeta_id = row['DataOwnerCode'] + '_' + row['LinePlanningNumber']
	destinationmeta_id = row['DataOwnerCode'] + '_' + row['DestinationCode']
	id = '_'.join([row['DataOwnerCode'], row['LocalServiceLevelCode'], row['LinePlanningNumber'], row['JourneyNumber'], row['FortifyOrderNumber']])
        pass_id = '_'.join([row['UserStopCode'], row['UserStopOrderNumber']])

	if id not in kv7cache or pass_id not in kv7cache[id]:
		if id not in kv7cache:
			kv7cache[id] = {pass_id : {'TargetArrivalTime' : toisotime(row['OperationDate'], row['TargetArrivalTime'], row)}}
		else:
			kv7cache[id][pass_id] = {'TargetArrivalTime' : toisotime(row['OperationDate'], row['TargetArrivalTime'], row)}
		kv7cache[id][pass_id]['TargetDepartureTime'] = toisotime(row['OperationDate'], row['TargetDepartureTime'], row)
		kv7cache[id][pass_id]['ProductFormulaType'] = row['ProductFormulaType']
		if destinationmeta_id not in destination_meta:
			destination_meta[destinationmeta_id] = row['DestinationName50']
		if linemeta_id not in line_meta:
			line_meta[linemeta_id] = { 'LineName' : row['LineName'], 'LinePublicNumber' : row['LinePublicNumber'], 'TransportType' : row['TransportType'], 'DataOwnerCode' : row['DataOwnerCode'], 'LinePlanningNumber' : row['LinePlanningNumber']}
        	storecurrect(row)
        	
def storemessage(row):
        id = '_'.join([row['DataOwnerCode'], row['MessageCodeDate'], row['MessageCodeNumber'], row['TimingPointDataOwnerCode'], row['TimingPointCode']])
        if row['TimingPointCode'] in tpc_store:
        	tpc_store[row['TimingPointCode']]['GeneralMessages'][id] = row
        else:
        	tpc_store[row['TimingPointCode']] = {'Passes' : {}, 'GeneralMessages' : {id : row}}
	generalmessagestore[id] = row

def deletemessage(row):
        id = '_'.join([row['DataOwnerCode'], row['MessageCodeDate'], row['MessageCodeNumber'], row['TimingPointDataOwnerCode'], row['TimingPointCode']])
        if row['TimingPointCode'] in tpc_store and id in tpc_store[row['TimingPointCode']]['GeneralMessages']:
        	del(tpc_store[row['TimingPointCode']]['GeneralMessages'][id])
        if id in generalmessagestore:
        	del(generalmessagestore[id])	
        
context = zmq.Context()

client = context.socket(zmq.REP)
client.bind(ZMQ_KV78UWSGI)

kv8 = context.socket(zmq.SUB)
kv8.connect(ZMQ_KV8)
kv8.setsockopt(zmq.SUBSCRIBE, "/GOVI/KV8")

kv7 = context.socket(zmq.PULL)
kv7.bind(ZMQ_KV7)

poller = zmq.Poller()
poller.register(client, zmq.POLLIN)
poller.register(kv8, zmq.POLLIN)
poller.register(kv7, zmq.POLLIN)

garbage = 0

while True:
    socks = dict(poller.poll())
    
    if socks.get(kv8) == zmq.POLLIN:
        multipart = kv8.recv_multipart()
        content = GzipFile('','r',0,StringIO(''.join(multipart[1:]))).read()
        c = ctx(content)
        if 'DATEDPASSTIME' in c.ctx:
            for row in c.ctx['DATEDPASSTIME'].rows():
            	    storecurrect(row)
        if 'GENERALMESSAGEUPDATE' in c.ctx:
            sys.stdout.write('MSGUPDATE')
            sys.stdout.flush()
            for row in c.ctx['GENERALMESSAGEUPDATE'].rows():
            	    storemessage(row)
        if 'GENERALMESSAGEDELETE' in c.ctx:
            sys.stdout.write('MSGDELETE')
            sys.stdout.flush()
            for row in c.ctx['GENERALMESSAGEDELETE'].rows():
            	    deletemessage(row)

    elif socks.get(kv7) == zmq.POLLIN:
    	data = kv7.recv_json()
        for pass_id, row in data.items():
        	storeplanned(row)

    elif socks.get(client) == zmq.POLLIN:
        url = client.recv()
        arguments = url.split('/')

        if arguments[0] == 'tpc':
            if len(arguments) == 1:
                reply = {}
                for tpc, values in tpc_store.items():
                	reply[tpc] = len(values['Passes'])
                client.send_json(reply)
            else:
                reply = {}
                for tpc in set(arguments[1].split(',')):
                    if tpc in tpc_store:
                        if tpc != '':
                            reply[tpc] = tpc_store[tpc]
                client.send_json(reply) 
                
        elif arguments[0] == 'journey':
            if len(arguments) == 1:
                reply = {}
                for journey, values in journey_store.items():
                	reply[journey] = len(values['Stops'])
                client.send_json(reply)
            else:
                reply = {}
                for journey in set(arguments[1].split(',')):
                    if journey in journey_store:
                        if journey != '':
                            reply[journey] = journey_store[journey]
                client.send_json(reply)
                
        elif arguments[0] == 'stopareacode':
            if len(arguments) == 1:
                reply = {}
                for stopareacode, values in stopareacode_store.items():
                	for tpc, tpcvalues in stopareacode_store[stopareacode].items():
                		reply[stopareacode] = tpc_meta[tpc]
                client.send_json(reply)
            else:
                reply = {}
                for stopareacode in set(arguments[1].split(',')):
                    if stopareacode in stopareacode_store:
                        if stopareacode != '':
                            reply[stopareacode] = stopareacode_store[stopareacode]
                client.send_json(reply)        	
                
        elif arguments[0] == 'line':
            if len(arguments) == 1:
                reply = {}
                for line, values in line_store.items():
                      reply[line] = values['Line']
                client.send_json(reply)
            else:
                reply = {}
                for line in set(arguments[1].split(',')):
                    if line in line_store and line != '':
                        reply[line] = line_store[line]
                client.send_json(reply)
                
        elif arguments[0] == 'lastupdate':
            reply = {'LastUpdateTimeStamps' : last_updatedataownerstore, 'ServerTime' : strftime("%Y-%m-%dT%H:%M:%SZ",gmtime())}
            client.send_json(reply)
            
        elif arguments[0] == 'generalmessage':
            client.send_json(generalmessagestore)
            
        else:
            client.send_json([])

    if garbage > 120:
        cleanup()
        sys.stdout.write('c')
        sys.stdout.flush()
        garbage = 0
    else:
        garbage += 1
