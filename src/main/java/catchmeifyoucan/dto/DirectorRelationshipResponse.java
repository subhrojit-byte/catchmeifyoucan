package catchmeifyoucan.dto;

import lombok.Getter;

import java.util.List;

@Getter
public class DirectorRelationshipResponse {
    private final Long directorId;
    private final String directorName;
    private final List<CompanyObservationResponse> associatedCompanies;

    public DirectorRelationshipResponse(
            Long directorId,
            String directorName,
            List<CompanyObservationResponse> associatedCompanies) {
        this.directorId = directorId;
        this.directorName = directorName;
        this.associatedCompanies = associatedCompanies;
    }
}
