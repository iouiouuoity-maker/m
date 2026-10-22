FROM python:3.12-slim
WORKDIR /app
COPY dist ./dist
COPY server ./server
RUN useradd --create-home app && mkdir /data && chown app:app /data
USER app
ENV ERRORMAP_DATA=/data PORT=8000
VOLUME ["/data"]
EXPOSE 8000
CMD ["python3", "server/start.py", "--host", "0.0.0.0"]
