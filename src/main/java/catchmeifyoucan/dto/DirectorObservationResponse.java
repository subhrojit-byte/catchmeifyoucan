package catchmeifyoucan.dto;

import catchmeifyoucan.entity.Director;
import lombok.Getter;

@Getter
public class DirectorObservationResponse {
    private final Long id;
    private final String name;

    public DirectorObservationResponse(Director director) {
        this.id = director.getId();
        this.name = director.getName();
    }
}
