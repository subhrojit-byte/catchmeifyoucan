package catchmeifyoucan.dto;

import catchmeifyoucan.entity.CompanyDirector;
import lombok.Getter;

@Getter
public class CompanyDirectorResponse {
    private final Long id;
    private final CompanyObservationResponse company;
    private final DirectorObservationResponse director;

    public CompanyDirectorResponse(CompanyDirector relationship) {
        this.id = relationship.getId();
        this.company = new CompanyObservationResponse(relationship.getCompany());
        this.director = new DirectorObservationResponse(relationship.getDirector());
    }
}
