FROM python:3.12-slim
WORKDIR /probe
RUN pip install --no-cache-dir camply==0.34.4
COPY probe.py test_probe.py ./
ENV PYTHONUNBUFFERED=1 HOME=/tmp CAMPLY_LOG_HANDLER=PYTHON
USER 65534:65534
CMD ["python", "probe.py"]
