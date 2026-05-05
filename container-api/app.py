# Author: Mahmoud Alnasir
# Affiliation: Lehrstuhl für Automatisierung und Energiesysteme (AES), Universität des Saarlandes
# Project: BaSyx-AutoTwin | EnFoSaar

                      

import os
import logging
import docker
from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime
import traceback

                       
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

                     
app = Flask(__name__)
CORS(app)                         

                              
def init_docker_client():
    try:
                                               
        client = docker.from_env()
        client.ping()
        logger.info("Docker-Client erfolgreich mit docker-controller verbunden (TCP)")
        return client
    except Exception as e1:
        logger.warning(f"Docker-Controller TCP fehlgeschlagen: {e1}")
        
        try:
                                              
            client = docker.DockerClient(base_url='tcp://docker-controller:2375')
            client.ping()
            logger.info("Docker-Client erfolgreich mit lokalem Socket verbunden")
            return client
        except Exception as e2:
            logger.warning(f"Lokaler Docker Socket fehlgeschlagen: {e2}")
            
            try:
                                                      
                client = docker.DockerClient(base_url='https://docker-controller:2375', tls=True)
                client.ping()
                logger.info("Docker-Client erfolgreich mit docker-controller verbunden (TLS)")
                return client
            except Exception as e3:
                logger.error(f"Alle Docker-Verbindungsversuche fehlgeschlagen:")
                logger.error(f"  TCP: {e1}")
                logger.error(f"  Socket: {e2}")
                logger.error(f"  TLS: {e3}")
                return None

docker_client = init_docker_client()

class ContainerManager:
    
    def __init__(self):
        self.client = docker_client
        
    def get_container_status(self, container_name):
        try:
            container = self.client.containers.get(container_name)
            return {
                'name': container.name,
                'status': container.status,
                'id': container.short_id,
                'image': container.image.tags[0] if container.image.tags else 'unknown',
                'created': container.attrs['Created'],
                'ports': container.ports,
                'health': self._get_health_status(container)
            }
        except docker.errors.NotFound:
            return {'error': f'Container {container_name} nicht gefunden'}
        except Exception as e:
            return {'error': str(e)}
        
    def get_container_sourcecode(self, container_name, filename=None):
        try:
            container = self.client.containers.get(container_name)
            
            if filename:
                                              
                file_path = f"/app/{filename}"
                exec_log = container.exec_run(f'cat {file_path}', stdout=True, stderr=True)
                if exec_log.exit_code == 0:
                    return {
                        'name': container.name,
                        'code': exec_log.output.decode('utf-8'),
                        'filename': filename
                    }
                else:
                    return {'error': f'Fehler beim Abrufen von {filename}: {exec_log.output.decode("utf-8")}'}
            
                                              
                                                                                  
            exec_ls = container.exec_run('ls /app', stdout=True, stderr=True)
            if exec_ls.exit_code != 0:
                return {'error': f'Fehler beim Auflisten des /app-Verzeichnisses: {exec_ls.output.decode("utf-8")}'}
            files = exec_ls.output.decode('utf-8').splitlines()
            py_files = [f for f in files if f.endswith('.py')]
            if not py_files:
                return {'error': f'Keine Python-Datei im /app-Verzeichnis von {container_name} gefunden'}
                                                   
            file_path = f"/app/{py_files[0]}"
            exec_log = container.exec_run(f'cat {file_path}', stdout=True, stderr=True)
            if exec_log.exit_code == 0:
                return {
                    'name': container.name,
                    'code': exec_log.output.decode('utf-8'),
                    'filename': py_files[0]
                }
            else:
                return {'error': f'Fehler beim Abrufen des Quellcodes: {exec_log.output.decode("utf-8")}'}
        except docker.errors.NotFound:
            return {'error': f'Container {container_name} nicht gefunden'}
        except Exception as e:
            return {'error': str(e)}    
    
    def _get_health_status(self, container):
        try:
            health = container.attrs.get('State', {}).get('Health', {})
            if health:
                return {
                    'status': health.get('Status', 'unknown'),
                    'failing_streak': health.get('FailingStreak', 0),
                    'log': health.get('Log', [])[-1] if health.get('Log') else None
                }
            return {'status': 'no-healthcheck'}
        except:
            return {'status': 'unknown'}
    
    def start_container(self, container_name):
        try:
            container = self.client.containers.get(container_name)
            if container.status != 'running':
                container.start()
                logger.info(f"Container {container_name} gestartet")
                return {'success': True, 'message': f'Container {container_name} gestartet'}
            else:
                return {'success': True, 'message': f'Container {container_name} läuft bereits'}
        except docker.errors.NotFound:
            return {'success': False, 'error': f'Container {container_name} nicht gefunden'}
        except Exception as e:
            logger.error(f"Fehler beim Starten von {container_name}: {e}")
            return {'success': False, 'error': str(e)}
    
    def stop_container(self, container_name):
        try:
            container = self.client.containers.get(container_name)
            if container.status == 'running':
                # Disable auto-restart before stopping so on-failure policy
                # does not bring the container back up after an intentional stop.
                try:
                    container.update(restart_policy={"Name": "no"})
                except Exception:
                    pass
                container.stop()
                logger.info(f"Container {container_name} gestoppt")
                return {'success': True, 'message': f'Container {container_name} gestoppt'}
            else:
                return {'success': True, 'message': f'Container {container_name} läuft nicht'}
        except docker.errors.NotFound:
            return {'success': False, 'error': f'Container {container_name} nicht gefunden'}
        except Exception as e:
            logger.error(f"Fehler beim Stoppen von {container_name}: {e}")
            return {'success': False, 'error': str(e)}
    
    def restart_container(self, container_name):
        try:
            container = self.client.containers.get(container_name)
            container.restart()
            logger.info(f"Container {container_name} neu gestartet")
            return {'success': True, 'message': f'Container {container_name} neu gestartet'}
        except docker.errors.NotFound:
            return {'success': False, 'error': f'Container {container_name} nicht gefunden'}
        except Exception as e:
            logger.error(f"Fehler beim Neustarten von {container_name}: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_container_logs(self, container_name, lines=100):
        try:
            container = self.client.containers.get(container_name)
            logs = container.logs(tail=lines, timestamps=True).decode('utf-8')
            return {'success': True, 'logs': logs}
        except docker.errors.NotFound:
            return {'success': False, 'error': f'Container {container_name} nicht gefunden'}
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Logs von {container_name}: {e}")
            return {'success': False, 'error': str(e)}

                                  
container_manager = ContainerManager()

              
                                                                         
                                      
                                         
          

                          
                                                              
                                                                    
           

                                                                   

                                        
                                                                                                                       
        
                                          
                                                                  
        
                                        
                                                                    
        
                                                      
                                
                                                                

                                                                                    
                                                              

                                                                                              
                                
                                
                                               
               
                                                                                                                                  

                        
                                                                                                                   

                                          
                                                    
                                                                         
        
                  
                              
                                                
                                    
                                             
           
                            
                                                                                            
                                                         

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        'service': 'Container Management API',
        'version': '1.0.0',
        'description': 'REST API für Docker-Container-Steuerung über BaSyx',
        'status': 'running',
        'docker_available': docker_client is not None,
        'timestamp': datetime.now().isoformat(),
        'endpoints': {
            'health': 'GET /health - Health Check',
            'containers': 'GET /containers - Alle Container auflisten',
            'status': 'GET /containers/{name}/status - Container-Status',
            'start': 'POST /containers/{name}/start - Container starten',
            'stop': 'POST /containers/{name}/stop - Container stoppen',
            'restart': 'POST /containers/{name}/restart - Container neu starten',
            'logs': 'GET /containers/{name}/logs?lines=100 - Container-Logs',
            'sourcecode': 'GET /containers/{name}/sourcecode - Quellcode aus Container lesen'
        },
        'examples': {
            'modbus_status': '/containers/modbus-server-basyx/status',
            'modbus_start': '/containers/modbus-server-basyx/start',
            'modbus_logs': '/containers/modbus-server-basyx/logs?lines=50',
            'battery-simulator-basyx_status': '/containers/battery-simulator-basyx/status',
            'battery-simulator-basyx_start': '/containers/battery-simulator-basyx/start',
            'battery-simulator-basyx_logs': '/containers/battery-simulator-basyx/logs?lines=50'
        }
    })

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'docker_available': docker_client is not None,
        'docker_connection': 'connected' if docker_client else 'failed'

    })

@app.route('/containers/<container_name>/sourcecode', methods=['GET'])
def get_sourcecode(container_name):
    if not docker_client:
        return jsonify({'error': 'Docker-Client nicht verfügbar'}), 500
    
    filename = request.args.get('file')
    raw_mode = request.args.get('raw', 'false').lower() == 'true'
    
    sourcecode = container_manager.get_container_sourcecode(container_name, filename)
    
    if 'error' in sourcecode:
        return jsonify({'success': False, 'error': sourcecode['error']}), 404
    
    if raw_mode:
                                                                
        from flask import Response
        return Response(sourcecode['code'], mimetype='text/plain')

    sourcecode['success'] = True
    return jsonify(sourcecode)

@app.route('/containers/<container_name>/status', methods=['GET'])
def get_status(container_name):
    if not docker_client:
        return jsonify({'error': 'Docker-Client nicht verfügbar'}), 500
    
    status = container_manager.get_container_status(container_name)
    return jsonify(status)

@app.route('/containers/<container_name>/start', methods=['POST'])
def start_container(container_name):
    if not docker_client:
        return jsonify({'error': 'Docker-Client nicht verfügbar'}), 500
    
    result = container_manager.start_container(container_name)
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code

@app.route('/containers/<container_name>/stop', methods=['POST'])
def stop_container(container_name):
    if not docker_client:
        return jsonify({'error': 'Docker-Client nicht verfügbar'}), 500
    
    result = container_manager.stop_container(container_name)
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code

@app.route('/containers/<container_name>/restart', methods=['POST'])
def restart_container(container_name):
    if not docker_client:
        return jsonify({'error': 'Docker-Client nicht verfügbar'}), 500
    
    result = container_manager.restart_container(container_name)
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code

@app.route('/containers/<container_name>/logs', methods=['GET'])
def get_logs(container_name):
    if not docker_client:
        return jsonify({'error': 'Docker-Client nicht verfügbar'}), 500
    
    lines = request.args.get('lines', 100, type=int)
    result = container_manager.get_container_logs(container_name, lines)
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code

@app.route('/containers', methods=['GET'])
def list_containers():
    if not docker_client:
        return jsonify({'error': 'Docker-Client nicht verfügbar'}), 500
    
    try:
        containers = []
        for container in docker_client.containers.list(all=True):
            containers.append({
                'name': container.name,
                'status': container.status,
                'id': container.short_id,
                'image': container.image.tags[0] if container.image.tags else 'unknown'
            })
        return jsonify({'containers': containers})
    except Exception as e:
        logger.error(f"Fehler beim Auflisten der Container: {e}")
        return jsonify({'error': str(e)}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'error': 'Endpunkt nicht gefunden',
        'message': 'Verfügbare Endpunkte finden Sie unter /',
        'requested_url': request.url
    }), 404

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unbehandelte Exception: {e}")
    logger.error(f"Request: {request.method} {request.url}")
    logger.error(traceback.format_exc())
    
    return jsonify({
        'error': 'Interner Serverfehler',
        'message': str(e),
        'timestamp': datetime.now().isoformat()
    }), 500

if __name__ == '__main__':
    logger.info("=== Container Management API ===")
    logger.info("Version: 1.0.0")
    logger.info("Für BaSyx Container-Steuerung")
    
                    
    app.run(
        host='0.0.0.0',
        port=8090,
        debug=False,
        threaded=True
    )