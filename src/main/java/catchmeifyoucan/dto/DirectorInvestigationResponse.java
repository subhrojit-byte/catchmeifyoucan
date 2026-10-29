package catchmeifyoucan.dto;

import lombok.Getter;

import java.util.List;

@Getter
public class DirectorInvestigationResponse {
    private final CompanyObservationResponse company;
    private final List<DirectorRelationshipResponse> directors;

    public DirectorInvestigationResponse(
            CompanyObservationResponse company,
            List<DirectorRelationshipResponse> directors) {
        this.company = company;
        this.directors = directors;
    }
}
