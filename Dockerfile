FROM python:3.12-slim
WORKDIR /app
COPY core.py adapter.py metro_web.py server.py ./
COPY static ./static
RUN useradd -m tracker && mkdir -p /app/data && chown tracker:tracker /app/data
USER tracker
ENV PORT=8787
EXPOSE 8787
VOLUME ["/app/data"]
CMD ["python", "server.py"]
