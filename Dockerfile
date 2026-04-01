FROM python:3.11-slim

# Instalar herramientas básicas y dependencias para compilar
RUN apt-get update && apt-get install -y \
    curl gnupg unixodbc-dev gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# Instalar Microsoft ODBC Driver 18 para SQL Server
RUN curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
 && curl https://packages.microsoft.com/config/debian/10/prod.list > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql17

# Establecer carpeta de trabajo
WORKDIR /app

# Copiar archivos de requisitos primero (mejor aprovechamiento de caché)
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copiar el resto del proyecto
COPY . .

# Exponer el puerto que usa la app (5050)
EXPOSE 5050

# Comando para iniciar la app Flask con Waitress
CMD ["python", "appBonus.py"]