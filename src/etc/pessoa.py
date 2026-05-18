class Pessoa:
    def __init__(self, evento: dict, last_pessoa = None):
        self.last_pessoa = last_pessoa # Inverse Linked List

        self.last_timestamp = evento.timestamp
        self.last_zone = evento.zone_id
        self.last_event = evento.event_type
        self.genero = evento.gender
        self.idade = evento.age_range
        self.linger_time = evento.duration_s