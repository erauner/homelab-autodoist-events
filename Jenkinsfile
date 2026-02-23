#!/usr/bin/env groovy
/**
 * Jenkinsfile for homelab-autodoist-events
 *
 * Validates the Python events worker and builds/pushes a container image.
 */

@Library('homelab') _

def podYaml = '''
apiVersion: v1
kind: Pod
metadata:
  labels:
    workload-type: ci-builds
spec:
  imagePullSecrets:
  - name: nexus-registry-credentials
  containers:
  - name: jnlp
    image: jenkins/inbound-agent:3355.v388858a_47b_33-3-jdk21
    resources:
      requests:
        cpu: 100m
        memory: 256Mi
      limits:
        cpu: 500m
        memory: 512Mi
  - name: python
    image: python:3.12-slim
    command: ['cat']
    tty: true
    resources:
      requests:
        cpu: 200m
        memory: 512Mi
      limits:
        cpu: 1000m
        memory: 1Gi
  - name: kaniko
    image: gcr.io/kaniko-project/executor:debug
    command: ['sleep', '3600']
    volumeMounts:
    - name: nexus-creds
      mountPath: /kaniko/.docker
    resources:
      requests:
        cpu: 500m
        memory: 1Gi
      limits:
        cpu: 1000m
        memory: 2Gi
  volumes:
  - name: nexus-creds
    secret:
      secretName: nexus-registry-credentials
      items:
      - key: config.json
        path: config.json
'''

pipeline {
    agent {
        kubernetes {
            yaml podYaml
        }
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        timeout(time: 15, unit: 'MINUTES')
        disableConcurrentBuilds()
    }

    environment {
        IMAGE_NAME = 'docker.nexus.erauner.dev/homelab/autodoist-events'
    }

    stages {
        stage('Setup') {
            steps {
                container('python') {
                    sh '''
                        echo "=== Installing uv ==="
                        pip install uv --quiet

                        echo "=== Installing dependencies ==="
                        uv sync --group dev

                        echo "=== Python version ==="
                        python --version
                    '''
                }
            }
        }

        stage('Test') {
            steps {
                container('python') {
                    sh '''
                        echo "=== Running tests ==="
                        uv run --group dev pytest -v --tb=short
                    '''
                }
            }
        }

        stage('Build Package') {
            steps {
                container('python') {
                    sh '''
                        echo "=== Building package ==="
                        uv build

                        echo "=== Verifying CLI entrypoint ==="
                        uv run autodoist-events --help
                    '''
                }
            }
        }

        stage('Build & Push Image') {
            when {
                anyOf {
                    branch 'main'
                    branch 'master'
                }
            }
            steps {
                container('kaniko') {
                    script {
                        def shortCommit = sh(script: 'echo $GIT_COMMIT | cut -c1-7', returnStdout: true).trim()
                        sh """
                            /kaniko/executor \
                                --context=\${WORKSPACE} \
                                --dockerfile=\${WORKSPACE}/Dockerfile \
                                --destination=${IMAGE_NAME}:${shortCommit} \
                                --destination=${IMAGE_NAME}:latest \
                                --cache=true \
                                --cache-repo=${IMAGE_NAME}/cache
                        """
                    }
                }
            }
        }
    }

    post {
        failure {
            script {
                homelab.notifyDiscordFailure()
            }
        }
    }
}
