# set base image (host OS)
FROM zaandahl/megadetector:4.1

# set the working directory in the container
WORKDIR /code

# copy code
COPY src/ .

# run metadata_writer on start
CMD [ "python", "./mewc_box.py" ]