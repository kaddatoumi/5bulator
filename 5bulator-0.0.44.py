#!/usr/bin/python3

import os
import re
import sys
import argparse
import logging
from dataclasses import dataclass
import ipaddress
from collections import deque
import xlsxwriter
from typing import List
import pprint as pp
import copy
import dataclasses

#batch processing:
#bash$ for file in ../5health/*_bigip.conf; do ./5bulator-0.0.31.py -f $file -a YY; done

logging.basicConfig(level=logging.ERROR)

global autoacceptvalue, autoaccept, iruleList

autoaccept = True # auto respond to prompt for overwritting file
autoacceptvalue = True #overwrite or skip automatically when auto-accept and when prompted

#IPv6
#17067022_bigip.conf

#RD
#17067246_bigip.conf

configName ='bigip.conf'

configPath =''
xlsName ='bigip_conf.xlsx'

sourceFile = ''
targetFile = ''

lineCounter = 0
virtualCounter = 0
poolCounter = 0
iruleCounter = 0
policyCounter = 0

color1 = '95B3D7'
color2 = 'B8CCE4'
color3 = '365F91'

@dataclass
class member:
    hostname: str = 'none'
    address: str = 'none'
    port: str = 'none'
    
@dataclass
class pool:
    name: str = 'none'
    members = []
    method: str = 'round-robin'
    monitor: str = 'none'

@dataclass
class virtual:
    name: str = 'none'
    destination: str = 'none'
    port: str = 'none'
    mask: str = 'none'
    pool: str = 'none'
    snat: str = 'none'

@dataclass
class irule:
    name: str #= 'none'
    pools: List[str]
    nodes: List[str]

@dataclass
class policy:
    name: str #= 'none'
    pools: List[str]
    nodes: List[str]

iruleList =[]
policyList =[]

def yesnoPrompt(str,answer=None):
    if (answer==None):
        while(answer!='Y' and answer!='' and answer!='n'):
            answer=input(str)
            if(answer=='n'):
                return False
        return True
    elif(answer==True):
        print(str)
        return True
    elif(answer==False):
        print(str)
        exit(0)

def ipv6MaskToPrefix(str):
    bitCount = [0, 0x8000, 0xc000, 0xe000, 0xf000, 0xf800, 0xfc00, 0xfe00, 0xff00, 0xff80, 0xffc0, 0xffe0, 0xfff0, 0xfff8, 0xfffc, 0xfffe, 0xffff]
    count = 0
    try:
        for w in str.split(':'):
            if not w or int(w, 16) == 0: break
            count += bitCount.index(int(w, 16))
        logging.debug('prefix length for %s - %s', str, count)
        return count  
    except:
        raise SyntaxError('Bad NetMask')

def determineIpType(address):
    
    try:
        if type(ipaddress.ip_address((re.split('/',address)[0]))) is ipaddress.IPv4Address:
            return(4)
        elif type(ipaddress.ip_address((re.split('/',address)[0])))  is ipaddress.IPv6Address:
            return(6)
    except:
        #print('not an ip address, probably an fqdn')
        return(0)    

#Open bigip.conf, create spreadsheet and format it.
def initXLS():

    global cell_format, cell_format1, cell_format2, header_format
    global targetFile, sourceFile, xlsName, configName

    try:
        sourceFile = open(configName, 'r')
    except OSError:
        print ('Could not open/read orignal config file:', configName)
        sys.exit()

    #Make sure the file is readable

    try:
        line = sourceFile.readline()
    except:
        print ('This file doesn\'t appear to be readable:', configName)
        sys.exit()
    else:
        if not "#TMSH-VERSION:" in line:
            print("This file doesn't appear to be a bigip configuration file.")
            sys.exit()

    #Make sure the file is readable

    configPath=os.path.dirname(os.path.abspath(sourceFile.name))
    print('\n\tsource     :\t'+os.path.abspath(sourceFile.name))
    xlsName = configPath+'/'+os.path.basename(sourceFile.name)+'.xlsx'
    print('\tdestination:\t'+xlsName)

    if os.path.exists(xlsName):
        if autoaccept==False:
            if not yesnoPrompt("\n[?]"+xlsName+" already exists, do you want to overwrite this file (Y/n)?"):
                exit(0)
        if autoaccept==True:
            if autoacceptvalue==False:
                yesnoPrompt("\n[?]"+xlsName+" already exists, do you want to overwrite this file (Y/n)? n \nskipping "+xlsName, False)
                exit(0)
            elif autoacceptvalue==True:             
                yesnoPrompt("\n[?]"+xlsName+" already exists, do you want to overwrite this file (Y/n)? y", True)

    targetFile = xlsxwriter.Workbook(xlsName)

    cell_format1 = targetFile.add_format({'align': 'justify','valign': 'vcenter', 'bg_color': color1 })
    cell_format2 = targetFile.add_format({'align': 'justify','valign': 'vcenter', 'bg_color': color2 })
    header_format = targetFile.add_format({'align': 'justify','valign': 'vcenter', 'bg_color': color3, 'bold' : 'true', 'font_color' : 'white' })

    global virtualWorksheetXLS 
    virtualWorksheetXLS = targetFile.add_worksheet('virtual')
    virtualWorksheetXLS.set_column(1,2,30)
    virtualWorksheetXLS.set_column(3,3,15)
    virtualWorksheetXLS.set_column(4,5,30)

    global poolWorksheetXLS 
    poolWorksheetXLS = targetFile.add_worksheet('pools')
    poolWorksheetXLS.set_column(1,2,30)
    poolWorksheetXLS.set_column(3,3,20)
    poolWorksheetXLS.set_column(4,5,15)
    poolWorksheetXLS.set_column(6,6,30)

    printPoolHeaderXLS()
    printVirtualHeaderXLS()
    print('\n','Analyzing', configName, ':\n')

#Housecleaning, close opened files.
def terminateXLS():
    try:
        targetFile.close()
    except xlsxwriter.exceptions.FileCreateError:
        print ('Could not close spreadsheet file:', xlsName)
        sys.exit()

    try:
        sourceFile.close()
    except OSError:
        print ('Could not close orignal config file:', configName)
        sys.exit()
    print('\n',str(virtualCounter)+' virtuals and '+str(poolCounter)+' pools analyzed and exported in '+xlsName+'.')

#########################
#Config operations
#########################

def removeConfigSegment(configSegment, pattern):

    queue = deque([])
    patternMatched=False
    patternStart = re.compile(pattern)
    patternOpenBracket = re.compile('.*{.*')
    patternCloseBracket = re.compile('.*}.*')

    for line in configSegment.split('\n'):
       queue.append(line+'\n')
       if patternStart.search(line):
           patternMatched=True
       if patternCloseBracket.search(line):
           if(patternMatched==True):
                while patternOpenBracket.search(queue[-1])==None:
                    queue.pop()
                if(patternStart.search(queue[-1])!=None):
                    patternMatched=False
                queue.pop()
    
    resultConfigSegment=''.join(queue)

    return resultConfigSegment

def extractConfigSegment(configSegment, pattern):

    patternMatched=False
    patternStart = re.compile(pattern)
    patternOpenBracket = re.compile('.*{.*')
    patternCloseBracket = re.compile('.*}.*')
    patternNestedInline = re.compile('[\s]*.*{.*}.*')

    counterNest=0
    resultConfigSegment =''

    for line in configSegment.split('\n'):
       if patternStart.search(line):
           patternMatched=True
           counterNest+=1
           resultConfigSegment+=line+'\n'
       elif patternNestedInline.search(line):
           if(patternMatched and counterNest>0):
                resultConfigSegment+=line+'\n'
       elif patternCloseBracket.search(line):
           if(patternMatched and counterNest>0):
                resultConfigSegment+=line+'\n'
                counterNest-=1
                if(counterNest==0):
                    patternMatched=False
       elif patternOpenBracket.search(line):
           if(patternMatched and counterNest>0):
                resultConfigSegment+=line+'\n'
                counterNest+=1
       else:
           if(patternMatched and counterNest>0):
                resultConfigSegment+=line+'\n'

    return resultConfigSegment

#########################
#Pools
#########################

#Write column headers for pool members in the worksheet.
def printPoolHeaderXLS():
    global rowXLS
    rowXLS = 1
    poolWorksheetXLS.write(rowXLS, 1, 'Name', header_format)
    poolWorksheetXLS.write(rowXLS, 2, 'Hostnames', header_format)
    poolWorksheetXLS.write(rowXLS, 3, 'IP address', header_format )
    poolWorksheetXLS.write(rowXLS, 4, 'Port', header_format)
    poolWorksheetXLS.write(rowXLS, 5, 'Load Balancing Method', header_format)
    poolWorksheetXLS.write(rowXLS, 6, 'Monitor', header_format)
    rowXLS += 1

#Print the pool member passed as argument in the pool worksheet.
def printMemberXLS(member):
    if member!=None:
        poolWorksheetXLS.write(rowXLS, 2, member.hostname, cell_format )
        poolWorksheetXLS.write(rowXLS, 3, member.address, cell_format )
        poolWorksheetXLS.write(rowXLS, 4, member.port, cell_format )
    else:
        poolWorksheetXLS.write(rowXLS, 2, 'none', cell_format )
        poolWorksheetXLS.write(rowXLS, 3, 'none', cell_format )
        poolWorksheetXLS.write(rowXLS, 4, 'none', cell_format )    

#Print the pool information in the pool worksheet based on the pool configuration passed as argument.
def printPoolXLS(pool):
    global rowXLS, cell_format

    rowXLSstart = rowXLS
    numberOfMembers= len(pool.members)
    rowXLSend = rowXLS + numberOfMembers-1

    #If there are more than one member in the pool we merge col 1, 5 and 6 (name, lb method, monitor).

    if (lineCounter % 2) == 0:
        cell_format=cell_format1
    else:
        cell_format=cell_format2

    if (numberOfMembers>1):
        poolWorksheetXLS.merge_range(rowXLSstart, 1,rowXLSend ,1 ,pool.name, cell_format )
    else:    
        poolWorksheetXLS.write(rowXLS, 1, pool.name, cell_format )

    if len(pool.members)>0:
        printMemberXLS(pool.members[0])
    else:
         printMemberXLS(None)

    if (numberOfMembers>1):
        poolWorksheetXLS.merge_range(rowXLSstart, 5,rowXLSend ,5 ,pool.method, cell_format )
    else:    
        poolWorksheetXLS.write(rowXLS, 5, pool.method, cell_format )

    if (numberOfMembers>1):
        poolWorksheetXLS.merge_range(rowXLSstart, 6,rowXLSend ,6 ,pool.monitor, cell_format )
    else:    
        poolWorksheetXLS.write(rowXLS, 6, pool.monitor, cell_format )

    for member in pool.members[1:]:
        rowXLS += 1
        printMemberXLS(member)

    rowXLS += 1

#Parse bigip.conf and send a pool configuration for processing each time it matches a pool.
def scanPool():
    print('[*] Scanning bigip.conf for Pools.')
    global rowXLS, poolCounter 
    rowXLS=2
    sourceFile.seek(0)
    poolConfig = ''
    patternStart = re.compile('^ltm pool /')
    patternEnd = re.compile('^}$')
    for i, line in enumerate(sourceFile):
       if patternStart.search(line):
          poolConfig = line
          for j, line in enumerate(sourceFile, start=i):
             poolConfig += line 
             if patternEnd.search(line):
                poolCounter += 1
                processPoolConfig(poolConfig)
                break

#extact information from the pool configuration and send them for printing in worksheet.        
def processPoolConfig(poolConfig):

    poolConfig=trimPoolConfig(poolConfig)

    global lineCounter
    lineCounter += 1

    mhostnames = []
    mports = []
    maddresses = []

    #We separate Pool and Members configuration to ease parsing:
    memberConfig = extractConfigSegment(poolConfig,'([\s]*members\s{)')
    poolConfig   = removeConfigSegment(poolConfig,'([\s]*members\s{)')

    p = pool
    #########################
    #Pool parsing
    #########################
    #cannot add $ at the end of the regex, tbi
    pattern =re.compile(r'^ltm\spool\s(.*)\s{')
    name = pattern.findall(poolConfig)
    if name:
        if len(name)==1:
            p.name=name[0]
            poolConfig = pattern.sub('',poolConfig)
        else:
            print('[*] Syntax error in current pool, review configuration manually, skipping')
            return

    re.purge()
    pattern =re.compile(r'[\s]*monitor\s.*')
    monitor = pattern.findall(poolConfig)
    if monitor:
        if len(monitor)==1:
            p.monitor=re.sub('min [0-9] of { ','', monitor[0])
            p.monitor=re.sub('(^[\s]*monitor )','',p.monitor)
            p.monitor=p.monitor.replace(' and ', ' ').replace(' }', '')
            poolConfig = pattern.sub('',poolConfig)
        else:
            print('[*] Syntax error in current pool,'+ p.name +' review configuration manually, skipping')
            return

    re.purge()
    pattern =re.compile(r'[\s]*load-balancing-mode\s(.*)')
    method = pattern.findall(poolConfig)
    if method:
        if len(method)==1:
            p.method = method[0]
            poolConfig = pattern.sub('',poolConfig)
        else:
            print('[*] Syntax error in current pool,'+ p.name +' review configuration manually, skipping')
            return

    #########################
    #Member parsing
    #########################
    #couldn't find how to specify ^ before [\s] in the regex  tbi
    #handling ipv4 and v6 separately.
    re.purge()
    pattern =re.compile(r'[\s].*[\s]{\n[\s]*address\s.*')
    members =pattern.findall(memberConfig)
    
    if len(members)==0:
        if 'fqdn' in memberConfig:
            pattern =re.compile(r'[\s].*[\s]{\n[\s]*fqdn\s{\n.*')
            members =pattern.findall(memberConfig)
            for cmember in members:
                
                cmember = re.sub(' +', ' ', cmember)
                cmember = re.sub('\n', '', cmember)
                cmember = re.sub('{', '', cmember)
                cmember = re.sub('}', '', cmember)
                
                re.purge()
                pattern =re.compile(r'(.*):.* fqdn .*')
                hostname = pattern.findall(cmember)
                hostname = re.sub(' +', '',hostname[0])
                mhostnames.append(hostname)
                logging.debug('Pool Member fqdn hostname %s', hostname)
                poolConfig = pattern.sub('',memberConfig)
                
                re.purge()
                pattern =re.compile(r'.*:(.*) fqdn .*')
                port = pattern.findall(cmember)
                mports.append(port[0])
                logging.debug('Pool Member IPv4 port %s', port[0])
                poolConfig = pattern.sub('',memberConfig)
                
                re.purge()
                pattern =re.compile(r'.*:.*  fqdn  name (.*)')
                address = pattern.findall(cmember)
                maddresses.append(address[0])
                logging.debug('Pool Member IPv4 port %s', port[0])
                poolConfig = pattern.sub('',memberConfig)
                    #If pool is not empty we create it as p
                    
            if (len(maddresses))>0:
                for  i in range(0, len(maddresses)):
                    logging.debug('storing: %s %s %s', mhostnames[i], maddresses[i], mports[i]) 
                    m = member(mhostnames[i], maddresses[i], mports[i])    
                    p.members.append(m)
                
        else:
            pass
            #print('Error - no member detected in this pool')
    else:
        for cmember in members:
            cmember = re.sub(' +', ' ', cmember)
            cmember = re.sub('\n', '', cmember)
            logging.debug('member :'+ str(cmember))
            re.purge()
            pattern =re.compile(r'.*address\s(.*)')
            address = pattern.findall(cmember)
            
            #we remove the rd in order to be able to test the type of the address
            tmpaddress=re.sub('%[0-9]*', '',address[0])

            if determineIpType(tmpaddress)==4:
                maddresses.append(address[0])
                logging.debug('Pool Member IPv4 address %s', address[0])
                poolConfig = pattern.sub('',memberConfig)

                re.purge()
                pattern =re.compile(r'.*:(.*)\s{ address .*')
                port = pattern.findall(cmember)
                mports.append(port[0])
                logging.debug('Pool Member IPv4 port %s', port[0])
                poolConfig = pattern.sub('',memberConfig)

                re.purge()
                pattern =re.compile(r'(.*):.*\s{ address .*')
                hostname = pattern.findall(cmember)
                hostname = re.sub(' +', '',hostname[0])
                mhostnames.append(hostname)
                logging.debug('Pool Member IPv4 hostname %s', hostname)
                poolConfig = pattern.sub('',memberConfig)

            if determineIpType(tmpaddress)==6:
                maddresses.append(address[0])
                logging.debug('Pool Member IPv6 address %s', address[0])    
                poolConfig = pattern.sub('',memberConfig)

                re.purge()
                pattern =re.compile(r'.*\.(.*)\s{ address .*')
                port = pattern.findall(cmember)
 
                re.purge()
                pattern =re.compile(r'.*\.(.*)\s{ address .*')
                port = pattern.findall(cmember)
                
                # if no match above then Name format using IPv6 address . followed by port
                #/Common/2408:8606:1800:100:0:0:0:1.0 
                if len(port)==0:
                    re.purge()
                    pattern =re.compile(r'.*:(.*)\s{ address .*')
                    port = pattern.findall(cmember)
                    mports.append(port[0])
                    logging.debug('Pool Member IPv6 port %s', port)
                    poolConfig = pattern.sub('',memberConfig)
                
                    re.purge()
                    pattern =re.compile(r'(.*):.*\s{ address .*')
                    hostname = pattern.findall(cmember)
                    hostname = re.sub(' +', '',hostname[0])
                    mhostnames.append(hostname)
                    logging.debug('Pool Member IPv6 hostname %s', hostname)
                    poolConfig = pattern.sub('',memberConfig)

                else:
                    mports.append(port[0])
                    logging.debug('Pool Member IPv6 port %s', port)
                    poolConfig = pattern.sub('',memberConfig)

                    re.purge()
                    pattern =re.compile(r'(.*)\..*\s{ address .*')
                    hostname = pattern.findall(cmember)
                    hostname = re.sub(' +', '',hostname[0])
                    mhostnames.append(hostname)
                    logging.debug('Pool Member IPv6 hostname %s', hostname)
                    poolConfig = pattern.sub('',memberConfig)

        #If pool is not empty we create it as p
        if (len(maddresses))>0:
            for  i in range(0, len(maddresses)):
                logging.debug('storing: %s %s %s', mhostnames[i], maddresses[i], mports[i]) 
                m = member(mhostnames[i], maddresses[i], mports[i])    
                p.members.append(m)

    printPoolXLS(p)

    #Reset p otherwise it's not returned to initial value at next execution, 
    # #wrong way to do it TBI 
    p.name = 'none'
    p.members = []
    p.method = 'round-robin'
    p.monitor = 'none'

#Remove pool configuration that are not required for documentation
def trimPoolConfig(poolConfig):
    
    #https://clouddocs.f5.com/cli/tmsh-reference/latest/modules/ltm/ltm_pool.html

    #Commented lines are config statements that should not be trimmed as they are used when parsing the config
    #the rest can be removed to simplify the configuration parsing.
    #Pools
    poolConfig = re.sub('(^[\s]*all$)','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*allow-nat([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*allow-snat([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*app-service([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*autoscale-group-id([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*description([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*gateway-failsafe-device([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*ignore-persisted-weight([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*ip-tos-to-client([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*ip-tos-to-server([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*link-qos-to-client([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*link-qos-to-server([\n]|[\s].*))','',poolConfig, flags=re.M)
    #poolConfig = re.sub('(^[\s]*load-balancing-mode([\n]|[\s].*))','',poolConfig, flags=re.M)
    #poolConfig = re.sub('(^[\s]*members([\n]|[\s].*))','',poolConfig, flags=re.M)
    #poolConfig = re.sub('(^[\s]*members none([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*metadata([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*min-active-members([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*min-up-members([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*min-up-members-action([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*min-up-members-checking([\n]|[\s].*))','',poolConfig, flags=re.M)
    #poolConfig = re.sub('(^[\s]*monitor([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*profiles([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*queue-on-connection-limit([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*queue-depth-limit([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*queue-time-limit([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*reselect-tries([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*service-down-action([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*slow-ramp-time([\n]|[\s].*))','',poolConfig, flags=re.M)
    #Members        
    #poolConfig = re.sub('(^[\s]*address([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*app-service([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*connection-limit([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*description([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*dynamic-ratio([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*inherit-profile([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*logging([\n]|[\s].*))','',poolConfig, flags=re.M)
    #poolConfig = re.sub('(^[\s]*monitor([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*priority-group([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*profiles([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*rate-limit([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*ratio([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*session([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*state([\n]|[\s].*))','',poolConfig, flags=re.M)
    #poolConfig = re.sub('(^[\s]*fqdn {([\n]|[\s].*))','',poolConfig, flags=re.M)
    #poolConfig = re.sub('(^[\s]*name([\n]|[\s].*))','',poolConfig, flags=re.M)
    poolConfig = re.sub('(^[\s]*autopopulate([\n]|[\s].*))','',poolConfig, flags=re.M)

    #Remove empty lines:
    poolConfig = re.sub(r'\n\s*\n','\n',poolConfig,flags=re.M)

    return poolConfig

#########################
#Virtual Servers
#########################

#Write column headers for virtual members in the worksheet.
def printVirtualHeaderXLS():
    global rowXLS
    rowXLS = 1
    virtualWorksheetXLS.write(rowXLS, 1, 'Name', header_format)
    virtualWorksheetXLS.write(rowXLS, 2, 'Destination', header_format)
    virtualWorksheetXLS.write(rowXLS, 3, 'Port', header_format)
    virtualWorksheetXLS.write(rowXLS, 4, 'Pool', header_format)
    virtualWorksheetXLS.write(rowXLS, 5, 'SNAT', header_format)

#Print the virtual information in the virtual worksheet based on the virtual configuration passed as argument.
def printVirtualXLS(virtual):
    global cell_format ,rowXLS

    if (virtualCounter % 2) == 0:
        cell_format=cell_format1
    else:
        cell_format=cell_format2
  
    virtualWorksheetXLS.write(rowXLS, 1, virtual.name, cell_format )
    virtualWorksheetXLS.write(rowXLS, 2, virtual.destination, cell_format )
    virtualWorksheetXLS.write(rowXLS, 3, virtual.port, cell_format )
    virtualWorksheetXLS.write(rowXLS, 4, virtual.pool, cell_format )
    virtualWorksheetXLS.write(rowXLS, 5, virtual.snat, cell_format )

    rowXLS += 1

#Parse bigip.conf and send a virtual configuration for processing each time it matches a virtual.
def scanVirtual():
    print('[*] Scanning bigip.conf for virtuals.')
    global rowXLS
    rowXLS=2
    sourceFile.seek(0)
    virtualConfig = ''
    patternStart = re.compile('^ltm virtual /')
    patternEnd = re.compile('^}$')
    for i, line in enumerate(sourceFile):
       if patternStart.search(line):
          virtualConfig = line
          for j, line in enumerate(sourceFile, start=i):
             virtualConfig += line 
             if patternEnd.search(line):
                processVirtualConfig(virtualConfig)
                break

#extact atomic information from the virtual configuration and send them for printing in worksheet.         
def processVirtualConfig(virtualConfig):

    v = virtual
    v = virtual('none','none','none','none','none','none')

    #print('[DEBUG] VirtualConfig:', virtualConfig)

    virtualConfig=trimVirtualConfig(virtualConfig)
    global virtualCounter
    virtualCounter += 1

    #We separate Snat and Virtual configuration to ease parsing:
    snatConfig = extractConfigSegment(virtualConfig,'([\s]*source-address-translation\s{)')
    virtualConfig   = removeConfigSegment(virtualConfig,'([\s]*source-address-translation\s{)')

    irulesConfig = extractConfigSegment(virtualConfig,'([\s]*rules\s{)')
    policiesConfig = extractConfigSegment(virtualConfig,'([\s]*policies\s{)')

    re.purge()
    pattern =re.compile(r'^ltm[\s]virtual\s(.*)\s{')
    name = pattern.findall(virtualConfig)
    if name:
       v.name=name[0]
       logging.debug('Virtual Name %s', v.name)     
       virtualConfig = pattern.sub('',virtualConfig)

    re.purge()
    pattern =re.compile(r'[\s]*mask\s(.*)')
    mask = pattern.findall(virtualConfig)
    if(not mask):
        # the mask appears to miss from the configuration for ipv6 VS when the address is a host address (/128)
        logging.debug('Setting mask to /128')   
        mask.append('ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff')

    #########################
    #IPv4 Virtuals
    #########################
    if determineIpType(mask[0])==4 or mask[0]=='any':
        if mask[0]=='any':
            v.mask=0
        else:
            v.mask = ipaddress.IPv4Network('0.0.0.0/'+mask[0]).prefixlen
        logging.debug('Virtual mask ipv4 %s', mask)

        re.purge()
        pattern = re.compile(r'\n[\s]*destination\s(.*):.*')
        destination = pattern.findall(virtualConfig)
        if destination:
            v.destination=destination[0]

        v.destination+='/'
        v.destination+=str(v.mask)
        logging.debug('Virtual destination ipv4 %s', v.destination)

        re.purge()
        pattern = re.compile(r'\n[\s]*destination\s.*:(.*)')
        port = pattern.findall(virtualConfig)
        if port:
            v.port=port[0]
            virtualConfig = pattern.sub('',virtualConfig)
        logging.debug('Port %s', v.port)

    #########################
    #IPv6 Virtuals
    #########################
    elif determineIpType(mask[0])==6 or mask[0]=='any6':

        #########################
        #Mask
        #########################
        if mask[0]=='any6':
            v.mask=0
        elif(mask[0]!=''):
            v.mask=ipv6MaskToPrefix(mask[0])
        else:
            print('# the mask appears to miss from the configuration for ipv6 VS when the address is a host address (/128)')
            v.mask = '128'
        logging.debug('Virtual mask ipv6 %s', v.mask)

        #########################
        #Destination
        #########################
        re.purge()
        pattern = re.compile(r'\n[\s]*destination\s(.*)\..*')
        destination = pattern.findall(virtualConfig)
        if destination:
            v.destination=destination[0]

        v.destination+='/'
        v.destination+=str(v.mask)
        logging.debug('Virtual destination ipv6 %s', v.destination)

        #########################
        #port
        #########################
        re.purge()
        pattern = re.compile(r'\n[\s]*destination\s.*\.(.*)')
        port = pattern.findall(virtualConfig)
        if port:
            v.port=port[0]
            virtualConfig = pattern.sub('',virtualConfig)
        logging.debug('Port %s', v.port)

    else:
         logging.debug('Mask is abnormal %s', v.mask)       

    m = getPoolsFromIrulesOrPolicies(irulesConfig, 'irule')
    n = getPoolsFromIrulesOrPolicies(policiesConfig, 'policy')
    
    if m!=None:
        m_str='\n'.join(m)+'\n'
    else:
        m_str=''

    if n!=None:
        n_str='\n'.join(n)+'\n'
    else:
        n_str=''

    re.purge()
    pattern =re.compile(r'\n[\s]*pool\s(.*)')
    pool =pattern.findall(virtualConfig)
    if pool:
        v.pool = (pool[0]+m_str+n_str).strip('\n')
        virtualConfig = pattern.sub('',virtualConfig)
    else:
        v.pool = (m_str+n_str).strip('\n')   

    if snatConfig:
        re.purge()
        pattern =re.compile(r'\n[\s]*pool\s(.*)')
        pool =pattern.findall(snatConfig)
        if pool:
            v.snat=pool[0]
            snatConfig = pattern.sub('',snatConfig)
        else:
            re.purge()
            pattern =re.compile(r'\n[\s]*type\s(.*)')
            type =pattern.findall(snatConfig)
            if type:
                v.snat=type[0]
                snatConfig = pattern.sub('',snatConfig)

    printVirtualXLS(v)

    #Reset v otherwise not returned to initial value at next execution, TBI
    v = virtual('none','none','none','none','none','none')

#Remove pool configuration that are not required for documentation
def trimVirtualConfig(virtualConfig):

    #https://clouddocs.f5.com/cli/tmsh-reference/latest/modules/ltm/ltm_virtual.html
    #consider modifying regex to consider the strign being at the beginning of the line.

    #Processing, Removing anything not required for table creation
    virtualConfig = re.sub('(^[\s]*all$)','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*address-status([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*app-service([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = removeConfigSegment(virtualConfig,'([\s]*auth .*{)')
    virtualConfig = re.sub('(^[\s]*auto-discovery([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*auto-lasthop([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = removeConfigSegment(virtualConfig,'([\s]*clone-pools .*{)') 
    virtualConfig = re.sub('(^[\s]*clone-pools none$)','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*cmp-enabled([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*connection-limit([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*dhcp-relay$)','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*description([\n]|[\s].*))','',virtualConfig, flags=re.M)
    #virtualConfig = re.sub('(^[\s]*destination([\n]|[\s].*))','',virtualConfig, flags=re.M) # Do not remove comment, required for configuration analysis
    virtualConfig = re.sub('(^[\s]*eviction-protected([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*fallback-persistence([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*flow-eviction-policy([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*fw-enforced-policy([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*fw-staged-policy([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*gtm-score([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*ip-forward$)','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*ip-protocol([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*internal$)','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*l2-forward$)','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*last-hop-pool([\n]|[\s].*))','',virtualConfig, flags=re.M)
    #virtualConfig = re.sub('(^[\s]*mask([\n]|[\s].*))','',virtualConfig, flags=re.M) # Do not remove , required for configuration analysis
    virtualConfig = re.sub('(^[\s]*mirror([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*nat64([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*per-flow-request-access-policy([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = removeConfigSegment(virtualConfig,'([\s]*persist .*{)')  
    virtualConfig = re.sub('(^[\s]*persist none$)','',virtualConfig, flags=re.M)
    #virtualConfig = removeConfigSegment(virtualConfig,'([\s]*policies .*{)') # Do not remove comment, required for configuration analysis
    #virtualConfig = re.sub('(^[\s]*pool([\n]|[\s].*))','',virtualConfig, flags=re.M) # Do not remove comment, required for configuration analysis
    virtualConfig = removeConfigSegment(virtualConfig,'([\s]*profiles .*{)')
    virtualConfig = re.sub('(^[\s]*rate-class([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*rate-limit([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*rate-limit-mode([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*rate-limit-dst([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*rate-limit-src([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*related-rules none([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*reject$)','',virtualConfig, flags=re.M)
    #virtualConfig = removeConfigSegment(virtualConfig,'([\s]*rules {)')
    virtualConfig = removeConfigSegment(virtualConfig,'([\s]*security-nat-policy {)')
    virtualConfig = re.sub('(^[\s]*serverssl-use-sni([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*service-down-immediate-action([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*service-policy([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*snat([\n]|[\s].*))','',virtualConfig, flags=re.M)
    #virtualConfig = re.sub('(^[\s]*snatpool([\n]|[\s].*))','',virtualConfig, flags=re.M) # Do not remove comment, required for configuration analysis
    virtualConfig = re.sub('(^[\s]*source([\n]|[\s].*))','',virtualConfig, flags=re.M)
    #source-address-translation, moved to pre-processing refer to beginning of function, above.
    virtualConfig = re.sub('(^[\s]*source-port([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = removeConfigSegment(virtualConfig,'([\s]*traffic-classes {)')
    virtualConfig = re.sub('(^[\s]*translate-address([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*translate-port([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*transparent-nexthop([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = removeConfigSegment(virtualConfig,'([\s]*vlans {)')
    virtualConfig = re.sub('(^[\s]*vlans-disabled$)','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*vlans-enabled$)','',virtualConfig, flags=re.M)
    virtualConfig = removeConfigSegment(virtualConfig,'([\s]*metadata {)')
    
    #not sure these can appear in configuration, but they are documented, doesn't arm(maybe) to have them here.:
    virtualConfig = re.sub('(^[\s]*reset-stats virtual([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*fw-enforced-policy-rules([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*fw-staged-policy-rules([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*security-nat-rules([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*profiles([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*options:([\n]|[\s].*))','',virtualConfig, flags=re.M) #is there really an "option" statement
    virtualConfig = re.sub('(^[\s]*fw-context-stat$)','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*ip-intelligence-categories$)','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*port-misuse$)','',virtualConfig, flags=re.M)

    #others:
    virtualConfig = re.sub('(^[\s]*creation-time([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*vs-index([\n]|[\s].*))','',virtualConfig, flags=re.M)
    virtualConfig = re.sub('(^[\s]*last-modified-time([\n]|[\s].*))','',virtualConfig, flags=re.M)

    #Remove empty lines:
    virtualConfig = re.sub(r'\n\s*\n','\n',virtualConfig,flags=re.M)

    return virtualConfig

#####################################
#iRules And Policies functions
#####################################

def extractObjectFromiRuleOrPolicies(keyword, lines):
    p=[]
    for line in lines:
        if not line.startswith("#"):
            if keyword in line:
                if keyword=='pool':
                    pattern = r'\bpool\s+([^}]+)'
                if keyword=='node':
                    pattern = r'\bnode\s+([^}]+)' 
                m = re.search(pattern, line)
                if m is not None:
                    p.append(m.group(1).strip())    
    return p

def getPoolsFromIrulesOrPolicies(config, type):

    global iruleList, policyList

    if type=='irule':
        list1=iruleList
    elif type=='policy':
        list1=policyList
    else:
        exit

    j = config.splitlines()
    j = j[1:-1]

    sj = [s.replace('{ }', '').strip() for s in j]

    t = []
    for k in sj:
        for l in list1:
            if k == l.name:
                if len(l.pools)>0:
                    t.extend(l.pools)
                if len(l.nodes)>0:
                    t.extend(l.nodes)

    return [u+' (via '+type+')' for u in t]

#########################
#iRules
#########################

#Parse bigip.conf and look for irules passed as parameters.
def scanIrules():
    print('[*] Scanning bigip.conf for iRules.')
    global rowXLS, iruleCounter 
    sourceFile.seek(0)
    iruleConfig = ''
    patternStart = re.compile('^ltm rule /')
    patternEnd = re.compile('^}$')
    for i, line in enumerate(sourceFile):
       if patternStart.search(line):
          iruleConfig = line
          for j, line in enumerate(sourceFile, start=i):
             iruleConfig += line 
             if patternEnd.search(line):
                processIruleConfig(iruleConfig)
                break

def processIruleConfig(iruleConfig):
    iruleConfig=trimVirtualConfig(iruleConfig)
    global iruleCounter, iruleList
    iruleCounter += 1
    lines = iruleConfig.splitlines()
    name = lines.pop(0).replace('ltm rule','').replace('{','').strip()

    if len(lines)!=0:
        lines.pop(len(lines)-1)
        for i in range(len(lines)):
            lines[i] = lines[i].strip()

        p = list(dict.fromkeys((extractObjectFromiRuleOrPolicies('pool', lines))))
        n = list(dict.fromkeys((extractObjectFromiRuleOrPolicies('node', lines))))
    else:
        p = ''
        n = ''

    k = irule(name, p, n)
    iruleList.append(dataclasses.replace(k))

#########################
#Policies
#########################

#Parse bigip.conf and look for ltm policy passed as parameters.
def scanPolicy():
    print('[*] Scanning bigip.conf for Policies.')
    global rowXLS, iruleCounter 
    sourceFile.seek(0)
    policyConfig = ''
    patternStart = re.compile('^ltm policy /')
    patternEnd = re.compile('^}$')
    for i, line in enumerate(sourceFile):
       if patternStart.search(line):
          policyConfig = line
          for j, line in enumerate(sourceFile, start=i):
             policyConfig += line 
             if patternEnd.search(line):
                processPolicyConfig(policyConfig)
                break

def processPolicyConfig(policyConfig):
    policyConfig=trimVirtualConfig(policyConfig)
    global policyCounter, policyList
    policyCounter += 1
    lines = policyConfig.splitlines()
    name = lines.pop(0).replace('ltm policy','').replace('{','').strip()

    if len(lines)!=0:
        lines.pop(len(lines)-1)
        for i in range(len(lines)):
            lines[i] = lines[i].strip()
 
        p = list(dict.fromkeys((extractObjectFromiRuleOrPolicies('pool', lines))))
        n = list(dict.fromkeys((extractObjectFromiRuleOrPolicies('node', lines))))
    else:
        p = ''
        n = ''

    k = policy(name, p, n)
    policyList.append(dataclasses.replace(k))

#########################
#INIT
#########################

#Prepare Command Line Interface
def initCLI():
    global configName, partitionName, autoaccept, autoacceptvalue

    # Create the parser
    cli_parser = argparse.ArgumentParser(description='Consumes a bigip.conf, produces virtual and pool tables in an .xlsx spreadsheet.')

    # Add the arguments
    cli_parser.add_argument('-f', '--file', type=str, required=False, help='Path to configuration file (default: bigip.conf)')
    cli_parser.add_argument('-a', '--autoaccept', type=str, required=False, default='n', help='Accept Y/n prompt automatically (YY, Yn, n - default: n )')

    args = cli_parser.parse_args()
    if args.file:
        configName = args.file
    
    if args.autoaccept not in ['YY', 'Yn', 'n']:
        cli_parser.print_help()
        sys.exit(1)
    else:
        if args.autoaccept in ['YY','Yn']:
            if args.autoaccept in ['YY']:
                autoaccept = True
                autoacceptvalue = True
            elif args.autoaccept in ['Yn']:
                autoaccept = True
                autoacceptvalue = False
        elif args.autoaccept in ['n']:
            autoaccept = False
            autoacceptvalue = False

#execute each task sequentially
def main():
    initCLI()
    initXLS()
    scanIrules()
    scanPolicy()
    scanVirtual()
    scanPool()
    terminateXLS()

if __name__ == "__main__":

    main()
