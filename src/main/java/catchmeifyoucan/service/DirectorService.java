package catchmeifyoucan.service;

import catchmeifyoucan.entity.Director;
import catchmeifyoucan.repository.DirectorRepository;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class DirectorService {

    private final DirectorRepository directorRepository;

    public DirectorService(DirectorRepository directorRepository) {
        this.directorRepository = directorRepository;
    }

    public Director createDirector(Director director) {
        return directorRepository.save(director);
    }

    public List<Director> getAllDirectors() {
        return directorRepository.findAll();
    }

    public Director getDirector(Long id) {
        return directorRepository.findById(id).orElse(null);
    }
}